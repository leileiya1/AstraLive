"""Compatibility of the pinned FlashAttention 2.8.3 CUDA path, not a capacity claim."""


def validate_gpu(torch):
    if not torch.cuda.is_available():
        raise RuntimeError('GPU_UNAVAILABLE')
    # Upstream v2.8.3 supports Ampere/Ada/Hopper; Turing needs a different path.
    if torch.cuda.get_device_capability()[0] not in (8, 9):
        raise RuntimeError('GPU_ARCHITECTURE_UNSUPPORTED')

