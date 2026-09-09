import sys

MORSE_CODE_DICT = {
    '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E',
    '..-.': 'F', '--.': 'G', '....': 'H', '..': 'I', '.---': 'J',
    '-.-': 'K', '.-..': 'L', '--': 'M', '-.': 'N', '---': 'O',
    '.--.': 'P', '--.-': 'Q', '.-.': 'R', '...': 'S', '-': 'T',
    '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X', '-.--': 'Y',
    '--..': 'Z'
}

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    tokens = line.split()
    decoded = [MORSE_CODE_DICT[t] for t in tokens if t in MORSE_CODE_DICT]
    print("".join(decoded))

if __name__ == "__main__":
    main()
