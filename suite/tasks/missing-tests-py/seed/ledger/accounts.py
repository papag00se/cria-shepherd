"""A tiny double-entry ledger. No tests exist for this module yet."""


class InsufficientFunds(Exception):
    pass


class Ledger:
    def __init__(self):
        self._balances = {}
        self.entries = []

    def open_account(self, name, opening_balance=0.0):
        if name in self._balances:
            raise ValueError(f"account already exists: {name}")
        if opening_balance < 0:
            raise ValueError("opening balance cannot be negative")
        self._balances[name] = float(opening_balance)

    def balance(self, name):
        if name not in self._balances:
            raise KeyError(name)
        return self._balances[name]

    def deposit(self, name, amount):
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self._balances[self._known(name)] += float(amount)
        self.entries.append(("deposit", name, float(amount)))

    def withdraw(self, name, amount):
        if amount <= 0:
            raise ValueError("withdrawal must be positive")
        if self._balances[self._known(name)] < amount:
            raise InsufficientFunds(f"{name} has {self._balances[name]}, needs {amount}")
        self._balances[name] -= float(amount)
        self.entries.append(("withdraw", name, float(amount)))

    def transfer(self, src, dst, amount):
        self._known(src)
        self._known(dst)
        self.withdraw(src, amount)
        self.deposit(dst, amount)
        self.entries.append(("transfer", (src, dst), float(amount)))

    def total(self):
        return round(sum(self._balances.values()), 2)

    def _known(self, name):
        if name not in self._balances:
            raise KeyError(name)
        return name
