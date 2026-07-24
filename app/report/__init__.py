"""Report content: the audience-shaped intermediate representation that sits
between `PMIDataModel` and the renderers.

Exists so that "what the report says" can be produced, previewed as text and
revised *before* any binary is written — and so pptx, xlsx, docx, pdf and html
render the same content rather than each re-deriving it from the data model.
"""
