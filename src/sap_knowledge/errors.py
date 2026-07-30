"""Exceptions raised by the knowledge pipeline."""


class SapKnowledgeError(Exception):
    """Base exception for package errors."""


class InvalidODataPayloadError(SapKnowledgeError):
    """Raised when an OData response does not have the expected structure."""


class MissingEntityKeyError(InvalidODataPayloadError):
    """Raised when a response record is missing a configured key field."""


class RepeatedContinuationError(InvalidODataPayloadError):
    """Raised when a service repeats a continuation URL and would loop forever."""


class UnsafeContinuationUrlError(SapKnowledgeError):
    """Raised when a server-provided continuation URL violates the URL policy."""


class InvalidMetadataError(SapKnowledgeError):
    """Raised when an EDMX metadata document cannot be interpreted."""


class RecipeValidationError(SapKnowledgeError):
    """Raised when a source record does not satisfy its knowledge recipe."""


class CheckpointError(SapKnowledgeError):
    """Raised when durable synchronization state is invalid or incompatible."""


class ConfigurationError(SapKnowledgeError):
    """Raised when CLI configuration is missing, invalid, or unsafe."""


class OptionalDependencyError(SapKnowledgeError):
    """Raised when a requested integration dependency is not installed."""


class VectorIndexError(SapKnowledgeError):
    """Raised when embeddings or vector-index state violate their contract."""
