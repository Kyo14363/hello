def join_names(names):
    if isinstance(names, (str, bytes)):
        raise TypeError("names must be an iterable of str")
    parts = []
    for item in names:
        if not isinstance(item, str):
            raise TypeError("each name must be str")
        text = item.strip()
        if text:
            parts.append(text)
    count = len(parts)
    if count == 0:
        return ""
    if count == 1:
        return parts[0]
    if count == 2:
        return parts[0] + " and " + parts[1]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
