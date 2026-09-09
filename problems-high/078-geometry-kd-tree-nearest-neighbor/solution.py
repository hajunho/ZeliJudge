import sys

sys.setrecursionlimit(200000)

class KDNode:
    __slots__ = ['point', 'left', 'right', 'axis']
    def __init__(self, point, axis):
        self.point = point
        self.axis = axis
        self.left = None
        self.right = None

def build_kdtree(points, depth=0):
    if not points:
        return None
    axis = depth % 2
    points.sort(key=lambda p: p[axis])
    mid = len(points) // 2
    
    node = KDNode(points[mid], axis)
    node.left = build_kdtree(points[:mid], depth + 1)
    node.right = build_kdtree(points[mid + 1:], depth + 1)
    return node

def dist_sq(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return dx * dx + dy * dy

def query_nn(node, q_point, best_dist):
    if node is None:
        return best_dist
        
    d = dist_sq(node.point, q_point)
    if d < best_dist[0]:
        best_dist[0] = d
        if d == 0:
            return best_dist
            
    axis = node.axis
    diff = q_point[axis] - node.point[axis]
    
    near = node.left if diff < 0 else node.right
    far = node.right if diff < 0 else node.left
    
    query_nn(near, q_point, best_dist)
    
    if diff * diff < best_dist[0]:
        query_nn(far, q_point, best_dist)
        
    return best_dist

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    
    points = []
    idx = 2
    for _ in range(n):
        x = int(input_data[idx])
        y = int(input_data[idx + 1])
        points.append((x, y))
        idx += 2
        
    root = build_kdtree(points)
    
    out = []
    for _ in range(q):
        qx = int(input_data[idx])
        qy = int(input_data[idx + 1])
        idx += 2
        best = [float('inf')]
        query_nn(root, (qx, qy), best)
        out.append(str(best[0]))
        
    print('\n'.join(out))

if __name__ == '__main__':
    main()
