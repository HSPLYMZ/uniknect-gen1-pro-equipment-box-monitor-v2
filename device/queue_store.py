"""Bounded RAM outbox; publish success is not receiver acknowledgement."""


class Outbox:
    def __init__(self, limit):
        self.limit = limit
        self.items = []
        self.dropped = 0

    def put(self, topic, payload, priority=False):
        if self.limit <= 0:
            self.dropped += 1
            return
        if len(self.items) >= self.limit:
            victim = None
            for i, item in enumerate(self.items):
                if not item[2]:
                    victim = i
                    break
            if victim is None:
                if not priority:
                    self.dropped += 1
                    return
                victim = 0
            self.items.pop(victim)
            self.dropped += 1
        self.items.append((topic, payload, priority))

    def peek(self):
        return self.items[0] if self.items else None

    def sent(self):
        if self.items:
            self.items.pop(0)

    def __len__(self):
        return len(self.items)
