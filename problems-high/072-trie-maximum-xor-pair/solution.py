import sys

class Trie:
    def __init__(self):
        self.ch = [[-1, -1]]
        
    def insert(self, val):
        curr = 0
        for b in range(30, -1, -1):
            bit = (val >> b) & 1
            if self.ch[curr][bit] == -1:
                self.ch[curr][bit] = len(self.ch)
                self.ch.append([-1, -1])
            curr = self.ch[curr][bit]
            
    def query(self, val):
        curr = 0
        xor_sum = 0
        for b in range(30, -1, -1):
            bit = (val >> b) & 1
            want = bit ^ 1
            if self.ch[curr][want] != -1:
                xor_sum |= (1 << b)
                curr = self.ch[curr][want]
            else:
                curr = self.ch[curr][bit]
        return xor_sum

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    a = [int(x) for x in input_data[1:1+n]]
    
    trie = Trie()
    trie.insert(a[0])
    ans = 0
    for i in range(1, n):
        ans = max(ans, trie.query(a[i]))
        trie.insert(a[i])
        
    print(ans)

if __name__ == '__main__':
    main()
