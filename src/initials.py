def initials(name):
    if not isinstance(name, str):
        raise TypeError("name must be str")
    letters = []
    for word in name.split():
        letters.append(word[0].upper())
    return "".join(letters)
