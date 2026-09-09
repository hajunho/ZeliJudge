import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    
    hex_digits = []
    for i in range(0, len(line), 4):
        chunk = line[i:i+4]
        val = int(chunk, 2)
        hex_char = hex(val)[2:].upper()
        hex_digits.append(hex_char)
        
    print("".join(hex_digits))

if __name__ == "__main__":
    main()
