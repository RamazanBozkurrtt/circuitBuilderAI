class KnowledgeError(RuntimeError):
    """Base error for fail-closed knowledge operations."""


class UnsupportedDocumentError(KnowledgeError):
    pass


class DocumentExtractionError(KnowledgeError):
    pass


class EmptyDocumentError(DocumentExtractionError):
    pass


class MissingIndexError(KnowledgeError):
    pass


class EmbeddingError(KnowledgeError):
    pass


class InconsistentDocumentHashError(KnowledgeError):
    pass


class FactExtractionError(KnowledgeError):
    pass
