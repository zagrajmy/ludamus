import re

# Characters Django's default SlugField accepts. A run of anything else at the
# end of a path segment is junk: a stray dot from the end of a sentence, a
# closing paren, or an emoji that a chat/social autolinker greedily swallowed
# into the URL when a user pasted a link.
_TRAILING_JUNK = re.compile(r"[^A-Za-z0-9_-]+$")


# Trim trailing junk off the final segment of a path. Returns the cleaned,
# slash-normalised path, or None when there is nothing to recover (the final
# segment is already clean, or there is no slug-bearing segment). A segment
# that is entirely junk is dropped back to its parent.
def strip_trailing_junk(path: str) -> str | None:
    if not (segments := [segment for segment in path.split("/") if segment]):
        return None

    last = segments[-1]
    if (cleaned := _TRAILING_JUNK.sub("", last)) == last:
        return None

    kept = segments[:-1]
    if cleaned:
        kept.append(cleaned)
    result = "/" + "/".join(kept) + "/" if kept else "/"

    return result if result != path else None
