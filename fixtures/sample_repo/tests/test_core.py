import unittest

from demo_pkg.core import Greeter, LoudGreeter


class TestGreetings(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(Greeter("ada").greet(), "Hello, ada!")

    def test_loud(self):
        g = LoudGreeter("ada", 3)
        # base greet ends with '!' and volume adds three more
        self.assertEqual(g.greet(), "HELLO, ADA!!!!")

    def test_volume_stored(self):
        g = LoudGreeter("linus", 1)
        self.assertEqual(g.volume, 1)
        self.assertEqual(g.name, "linus")


if __name__ == "__main__":
    unittest.main()
