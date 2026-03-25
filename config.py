from os import getenv

from dotenv import load_dotenv


load_dotenv()

OPENAI_API_KEY = getenv("OPENAI_API_KEY")
DATABASE_URL = getenv("DATABASE_URL")
DATABASE_DIRECT_URL = getenv("DATABASE_DIRECT_URL")
CHROMA_PATH = getenv("CHROMA_PATH")
DATA_DIR = getenv("DATA_DIR")
POOL_MIN = getenv("POOL_MIN")
POOL_MAX = getenv("POOL_MAX")

for _key, _value in {
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "DATABASE_URL": DATABASE_URL,
    "DATABASE_DIRECT_URL": DATABASE_DIRECT_URL,
    "CHROMA_PATH": CHROMA_PATH,
    "DATA_DIR": DATA_DIR,
    "POOL_MIN": POOL_MIN,
    "POOL_MAX": POOL_MAX,
}.items():
    if _value is None:
        raise ValueError(f"Missing required environment variable: {_key}")


if __name__ == "__main__":
    print(OPENAI_API_KEY)
    print(DATABASE_URL)
    print(DATABASE_DIRECT_URL)
    print(CHROMA_PATH)
    print(DATA_DIR)
    print(POOL_MIN)
    print(POOL_MAX)
