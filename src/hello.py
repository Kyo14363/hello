import sys


def greet():
    return "Hello, Gitmy! 👋"


def farewell(name):
    return "Goodbye, " + name + "! 👋"


def greet_name(name):
    return "Hello, " + name + "! 👋"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0]:
        print(greet_name(argv[0]))
    else:
        print(greet())


if __name__ == "__main__":
    main()
