import gzip
import lzma
import struct

try:
    import brotli
except ImportError:
    brotli = None

try:
    import lz4.block
except ImportError:
    lz4 = None

GZIP_MAGIC: bytes = b"\x1f\x8b"
BROTLI_MAGIC: bytes = b"brotli"


# LZMA
def decompress_lzma(data: bytes) -> bytes:
    """decompresses lzma-compressed data

    :param data: compressed data
    :type data: bytes
    :raises _lzma.LZMAError: Compressed data ended before the end-of-stream marker was reached
    :return: uncompressed data
    :rtype: bytes
    """
    props, dict_size = struct.unpack("<BI", data[:5])
    lc = props % 9
    props = props // 9
    pb = props // 5
    lp = props % 5
    dec = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": lc,
                "lp": lp,
                "pb": pb,
            }
        ],
    )
    return dec.decompress(data[5:])


def compress_lzma(data: bytes) -> bytes:
    """compresses data via lzma (unity specific)
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    ec = lzma.LZMACompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {"id": lzma.FILTER_LZMA1, "dict_size": 524288, "lc": 3, "lp": 0, "pb": 2, }
        ],
    )
    ec.compress(data)
    return b"]\x00\x00\x08\x00" + ec.flush()


# LZ4
def decompress_lz4(data: bytes, uncompressed_size: int) -> bytes:
    if lz4 is None:
        raise ImportError("lz4 not installed. Run: pip install lz4")
    return lz4.block.decompress(data, uncompressed_size)


def compress_lz4(data: bytes) -> bytes:
    if lz4 is None:
        raise ImportError("lz4 not installed. Run: pip install lz4")
    return lz4.block.compress(
        data, mode="high_compression", compression=9, store_size=False
    )


def decompress_brotli(data: bytes) -> bytes:
    if brotli is None:
        raise ImportError("brotli not installed. Run: pip install brotli")
    return brotli.decompress(data)


def compress_brotli(data: bytes) -> bytes:
    if brotli is None:
        raise ImportError("brotli not installed. Run: pip install brotli")
    return brotli.compress(data)


# GZIP
def decompress_gzip(data: bytes) -> bytes:
    """decompresses gzip-compressed data

    :param data: compressed data
    :type data: bytes
    :raises OSError: Not a gzipped file
    :return: uncompressed data
    :rtype: bytes
    """
    return gzip.decompress(data)


def compress_gzip(data: bytes) -> bytes:
    """compresses data via gzip
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: bytes
    :return: compressed data
    :rtype: bytes
    """
    return gzip.compress(data)
