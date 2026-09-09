import sys

def decrypt(cipher, k):
    res = []
    for ch in cipher:
        shifted = chr((ord(ch) - ord('A') - k) % 26 + ord('A'))
        res.append(shifted)
    return "".join(res)

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    c = lines[0].strip()
    w = lines[1].strip()
    
    for k in range(26):
        decrypted = decrypt(c, k)
        if w in decrypted:
            print(k)
            return

if __name__ == "__main__":
    main()
