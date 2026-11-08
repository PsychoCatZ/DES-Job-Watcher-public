"""Ввод секрета в Windows-консоли с видимыми звёздочками."""

import sys
from getpass import getpass


def read_secret(prompt):
    if sys.platform != 'win32':
        return getpass(prompt)
    import msvcrt

    if not sys.stdin.isatty():
        raise ValueError('Для скрытого ввода открой обычный интерактивный терминал.')
    print(prompt, end='', flush=True)
    characters = []
    while True:
        character = msvcrt.getwch()
        if character in ('\r', '\n'):
            print()
            return ''.join(characters)
        if character == '\x03':
            print()
            raise KeyboardInterrupt
        if character in ('\x00', '\xe0'):
            msvcrt.getwch()
            continue
        if character == '\b':
            if characters:
                characters.pop()
                print('\b \b', end='', flush=True)
        elif character == '\x15':
            print('\b \b' * len(characters), end='', flush=True)
            characters.clear()
        elif character.isprintable():
            characters.append(character)
            print('*', end='', flush=True)
