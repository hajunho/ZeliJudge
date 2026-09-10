import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class VirtioBalloonEngine:
    def __init__(self, config):
        self.total_pages = config.get('total_pages', 64)
        self.max_order = config.get('max_order', 6)
        self.min_reporting_order = config.get('min_reporting_order', 2)
        
        self.free_area = [{} for _ in range(self.max_order)]
        
        cur = 0
        rem = self.total_pages
        for ord in range(self.max_order - 1, -1, -1):
            sz = 1 << ord
            while rem >= sz:
                self.free_area[ord][cur] = {'reported': False}
                cur += sz
                rem -= sz
                
        self.allocations = {}
        self.balloon_blocks = []
        self.host_rss_pages = self.total_pages
        self.total_reported_events = 0
        self.total_reported_pages = 0

    def alloc_block(self, order):
        found_ord = -1
        for o in range(order, self.max_order):
            if self.free_area[o]:
                found_ord = o
                break
        if found_ord == -1:
            return None, False
            
        pfn = min(self.free_area[found_ord].keys())
        blk = self.free_area[found_ord].pop(pfn)
        was_rep = blk['reported']
        
        while found_ord > order:
            found_ord -= 1
            sz = 1 << found_ord
            buddy_pfn = pfn + sz
            self.free_area[found_ord][buddy_pfn] = {'reported': was_rep}
            
        if was_rep:
            self.host_rss_pages += (1 << order)
            
        return pfn, was_rep

    def free_block(self, pfn, order):
        while order < self.max_order - 1:
            buddy_pfn = pfn ^ (1 << order)
            if buddy_pfn in self.free_area[order]:
                self.free_area[order].pop(buddy_pfn)
                pfn = min(pfn, buddy_pfn)
                order += 1
            else:
                break
        self.free_area[order][pfn] = {'reported': False}
        return pfn, order

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'ALLOC_PAGES':
                aid = op['alloc_id']
                ord = op['order']
                pfn, was_rep = self.alloc_block(ord)
                if pfn is None:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'alloc_id': aid, 'error': 'ENOMEM_BUDDY_DEPLETED'})
                else:
                    self.allocations[aid] = {'pfn': pfn, 'order': ord}
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'alloc_id': aid, 'pfn': pfn, 'order': ord, 'pages': (1 << ord), 'was_reported': was_rep})
            elif t == 'FREE_PAGES':
                aid = op['alloc_id']
                if aid not in self.allocations:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'alloc_id': aid, 'error': 'ENOENT_ALLOC_NOT_FOUND'})
                else:
                    info = self.allocations.pop(aid)
                    coalesced_pfn, final_ord = self.free_block(info['pfn'], info['order'])
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'alloc_id': aid, 'coalesced_pfn': coalesced_pfn, 'final_order': final_ord, 'coalesced_pages': (1 << final_ord)})
            elif t == 'TRIGGER_REPORTING':
                rep_blks = []
                newly_rep = 0
                for ord in range(self.min_reporting_order, self.max_order):
                    for pfn in sorted(self.free_area[ord].keys()):
                        blk = self.free_area[ord][pfn]
                        if not blk['reported']:
                            blk['reported'] = True
                            sz = 1 << ord
                            newly_rep += sz
                            rep_blks.append({'pfn': pfn, 'order': ord, 'pages': sz})
                self.host_rss_pages = max(0, self.host_rss_pages - newly_rep)
                self.total_reported_events += 1
                self.total_reported_pages += newly_rep
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS',
                    'reported_blocks_count': len(rep_blks),
                    'newly_reported_pages': newly_rep,
                    'host_rss_pages': self.host_rss_pages,
                    'reported_blocks': rep_blks
                })
            elif t == 'INFLATE_BALLOON':
                target_pages = op['pages']
                inflated = 0
                while inflated < target_pages:
                    pfn, _ = self.alloc_block(0)
                    if pfn is None:
                        break
                    self.balloon_blocks.append((pfn, 0))
                    inflated += 1
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS' if inflated == target_pages else 'PARTIAL',
                    'requested_pages': target_pages,
                    'inflated_pages': inflated,
                    'current_balloon_pages': len(self.balloon_blocks)
                })
            elif t == 'DEFLATE_BALLOON':
                target_pages = op['pages']
                deflated = 0
                while deflated < target_pages and self.balloon_blocks:
                    pfn, ord = self.balloon_blocks.pop()
                    self.free_block(pfn, ord)
                    deflated += (1 << ord)
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS',
                    'requested_pages': target_pages,
                    'deflated_pages': deflated,
                    'current_balloon_pages': len(self.balloon_blocks)
                })
            elif t == 'QUERY_STATE':
                guest_alloc = sum(1 << a['order'] for a in self.allocations.values())
                balloon_sz = sum(1 << b[1] for b in self.balloon_blocks)
                free_unrep = 0
                free_rep = 0
                for ord in range(self.max_order):
                    for blk in self.free_area[ord].values():
                        if blk['reported']:
                            free_rep += (1 << ord)
                        else:
                            free_unrep += (1 << ord)
                results.append({
                    'op_index': idx,
                    'type': t,
                    'total_pages': self.total_pages,
                    'guest_allocated_pages': guest_alloc,
                    'balloon_pages': balloon_sz,
                    'guest_free_pages': free_rep + free_unrep,
                    'reported_free_pages': free_rep,
                    'unreported_free_pages': free_unrep,
                    'host_rss_pages': self.host_rss_pages
                })

        guest_alloc = sum(1 << a['order'] for a in self.allocations.values())
        balloon_sz = sum(1 << b[1] for b in self.balloon_blocks)
        free_unrep = 0
        free_rep = 0
        for ord in range(self.max_order):
            for blk in self.free_area[ord].values():
                if blk['reported']:
                    free_rep += (1 << ord)
                else:
                    free_unrep += (1 << ord)
                    
        summary = {
            'total_operations': len(ops),
            'final_host_rss_pages': self.host_rss_pages,
            'final_guest_allocated_pages': guest_alloc,
            'final_balloon_pages': balloon_sz,
            'final_reported_free_pages': free_rep,
            'final_unreported_free_pages': free_unrep,
            'total_reported_events': self.total_reported_events,
            'total_reported_pages': self.total_reported_pages
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = VirtioBalloonEngine(data.get('config', {}))
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
