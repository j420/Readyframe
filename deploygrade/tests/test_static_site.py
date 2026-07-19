import unittest

from deploygrade.harness.verify_static_site import main


class StaticSiteVerificationTests(unittest.TestCase):
    def test_checked_in_vercel_static_input_is_valid(self):
        main()
