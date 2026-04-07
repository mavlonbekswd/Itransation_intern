import hashlib
from pathlib import Path

FOLDER = Path("Task_2/task2")  # current folder
EMAIL = "mavlonbeksultanbekov3@gmail.com".lower()

HEX_MAP = {ch: int(ch, 16) for ch in "0123456789abcdef"}

def sha3_256_file(path):
    h = hashlib.sha3_256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def sort_key(hash_str):
    result = 1
    for ch in hash_str:
        result *= (HEX_MAP[ch] + 1)
    return result

# get only .data files
files = list(FOLDER.glob("*.data"))

print("Files found:", len(files))

if len(files) != 256:
    print("ERROR: Must be exactly 256 files")
    exit()

# hash each file
hashes = [sha3_256_file(f) for f in files]

# sort
hashes_sorted = sorted(hashes, key=lambda h: (sort_key(h), h))

# join without separator
joined = "".join(hashes_sorted)

# append email
final_input = joined + EMAIL

# final hash
final_hash = hashlib.sha3_256(final_input.encode()).hexdigest()

print("\nFINAL HASH:")
print(final_hash)

print("\nSUBMIT THIS:")
print(f"!task2 {EMAIL} {final_hash}")