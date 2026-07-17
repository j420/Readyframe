import json
import unittest
from pathlib import Path


ROOT = Path('.')
DASHBOARD = ROOT / 'deploygrade/sites/dashboard'


class VercelCompatibilityTests(unittest.TestCase):
    def test_vercel_serves_only_the_static_dashboard_with_required_headers(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        self.assertEqual(config['outputDirectory'], 'deploygrade/sites/dashboard')
        self.assertTrue(DASHBOARD.is_dir())
        for asset in ('index.html', 'app.js', 'styles.css', 'readiness_score.json', 'portfolio.json'):
            self.assertTrue((DASHBOARD / asset).is_file(), asset)

        headers = {item['key']: item['value'] for item in config['headers'][0]['headers']}
        policy = headers['Content-Security-Policy']
        self.assertIn("default-src 'self'", policy)
        self.assertIn("script-src 'self'", policy)
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("style-src 'self' 'unsafe-inline'", policy)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
