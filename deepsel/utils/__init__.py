import string
import random

def generate_recovery_codes(num_codes=16, code_length=10):
    codes = []
    for _ in range(num_codes):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=code_length))
        codes.append(code)
    return codes