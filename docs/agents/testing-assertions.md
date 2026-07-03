# Testing Assertions

## File Structure

```text
tests/integration/web/{namespace}/test_{url_name}.py
```

## Fixtures

Available via pytest-factoryboy:

| Fixture                    | Description             |
| -------------------------- | ----------------------- |
| `authenticated_client`     | Logged-in client        |
| `staff_client`             | Staff user client       |
| `active_user`              | Standard test user      |
| `staff_user`               | User with is_staff=True |
| `event`, `sphere`, `space` | Common entities         |
| `proposal`, `session`      | Event-related data      |

## assert_response

Always use for view tests. Never manual status/template assertions.

```python
assert_response(
    response,
    status=200,
    template="namespace/page.html",
    context_data={...},  # ALL keys, exact equality
    messages=[(messages.SUCCESS, "Saved.")],  # optional
)
```

## ANY usage

Reserve for hard-to-compare objects: forms, views.

Don't use for: `[]`, `{}`, booleans, simple values.

## Login redirects

Exact URL match:

```python
url=f"/crowd/login-required/?next={url}"
```

Never substring matching.

## Magic numbers

Use `1 + 1` pattern with comment:

```python
assert len(fields) == 1 + 1  # Email + Phone
```

## Context data

Views send DTOs/dataclasses to templates, never Django models. Tests verify DTO
attributes.
