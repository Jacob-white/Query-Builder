import pytest

from query_builder import (
    CompilationError,
    DialectError,
    QueryBuilderError,
    SecurityError,
    ValidationError,
)
from query_builder.exceptions import (
    CompilationError as DirectCompilationError,
)
from query_builder.exceptions import (
    DialectError as DirectDialectError,
)
from query_builder.exceptions import (
    QueryBuilderError as DirectQueryBuilderError,
)
from query_builder.exceptions import (
    SecurityError as DirectSecurityError,
)
from query_builder.exceptions import (
    ValidationError as DirectValidationError,
)


def test_exception_hierarchy():
    assert issubclass(CompilationError, QueryBuilderError)
    assert issubclass(ValidationError, CompilationError)
    assert issubclass(ValidationError, QueryBuilderError)
    assert issubclass(SecurityError, CompilationError)
    assert issubclass(SecurityError, QueryBuilderError)
    assert issubclass(DialectError, QueryBuilderError)


def test_exception_identities():
    assert CompilationError is DirectCompilationError
    assert ValidationError is DirectValidationError
    assert SecurityError is DirectSecurityError
    assert DialectError is DirectDialectError
    assert QueryBuilderError is DirectQueryBuilderError


def test_exception_instantiation_and_catch():
    with pytest.raises(QueryBuilderError) as exc_base:
        raise ValidationError("Schema field invalid")
    assert isinstance(exc_base.value, CompilationError)
    assert isinstance(exc_base.value, ValidationError)
    assert "Schema field invalid" in str(exc_base.value)

    with pytest.raises(CompilationError) as exc_comp:
        raise SecurityError("AST mutation disallowed")
    assert isinstance(exc_comp.value, SecurityError)
    assert isinstance(exc_comp.value, QueryBuilderError)
    assert "AST mutation disallowed" in str(exc_comp.value)

    with pytest.raises(QueryBuilderError) as exc_dial:
        raise DialectError("Invalid identifier name")
    assert isinstance(exc_dial.value, DialectError)
    assert not isinstance(exc_dial.value, CompilationError)
