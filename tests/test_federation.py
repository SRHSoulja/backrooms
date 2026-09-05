import json
import tempfile
import unittest
from pathlib import Path

from scripts import federation


PEER_FEED = {"records": [
    {"id": "p-1", "status": "unreviewed", "lifecycle_stage": "candidate", "claim": "Roskomnadzor blocked GitHub in December 2014 over pages about suicide.",
     "quote": "Roskomnadzor blocked access to GitHub in December 2014 after the site hosted pages about suicide", "url": "https://meduza.io/en/news/2014/12/03/github",
     "content_hash": "peerhash1", "topic": "roskomnadzor github block", "cycle": 40, "agent": "local-003"},
    {"id": "p-2", "status": "rejected", "claim": "x", "quote": "y" * 30, "url": "https://a.example/x"},
    {"id": "p-3", "status": "unreviewed", "claim": "The word under is a preposition.", "quote": "under is a preposition meaning beneath something", "url": "https://dictionary.cambridge.org/dictionary/english/under"},
    {"id": "p-4", "status": "unreviewed", "claim": "Same passage as ours.", "quote": "GitHub contributions may not appear unless manually rebuilt by GitHub Support", "url": "https://devactivity.com/insights/x"},
    {"id": "p-5", "status": "unreviewed", "claim": "A quote the source no longer has.", "quote": "this sentence is nowhere on the page at all", "url": "https://b.example/gone"},
]}


class FederationTests(unittest.TestCase):
    def test_peers_are_validated_and_feeds_read_only_accepted_records(self):
        with tempfile.TemporaryDirectory() as directory:
            peers = Path(directory) / "peers.json"
            peers.write_text(json.dumps({"peers": [{"name": "Backrooms Two", "url": "https://two.example/backrooms/"},
                                                    {"name": "two", "url": "https://two.example/backrooms/"},
                                                    {"name": "bad", "url": "http://plain.example"},
                                                    {"name": "creds", "url": "https://user:pw@x.example"}]}))
            self.assertEqual(federation.load_peers(peers), [{"name": "two", "url": "https://two.example/backrooms"}])
        self.assertEqual([item["id"] for item in federation.peer_findings(PEER_FEED)], ["p-1", "p-3", "p-4", "p-5"])

    def test_eligibility_applies_source_rules_and_dedupes_against_the_own_ledger(self):
        own = [{"url": "https://devactivity.com/insights/x", "claim": "Different claim", "quote": "GitHub contributions may not appear unless manually rebuilt by GitHub Support"}]
        rows = {item["id"]: item for item in federation.peer_findings(PEER_FEED)}
        self.assertEqual(federation.eligible(rows["p-1"], own), (True, ""))
        self.assertEqual(federation.eligible(rows["p-3"], own)[1], "dictionary source")
        self.assertEqual(federation.eligible(rows["p-4"], own)[1], "this world already quotes that passage")
        self.assertEqual(federation.eligible({"claim": "c", "quote": "short", "url": "https://x.example/a"}, own)[1], "no claim or a quote too short to re-verify")
        self.assertEqual(federation.eligible({"claim": "c", "quote": "long enough quote here ok", "url": "https://github.com/someone"}, own)[1], "an individual's account or profile")

    def test_federate_imports_only_what_its_own_fetch_confirms_and_never_twice(self):
        pages = {"https://meduza.io/en/news/2014/12/03/github": "News. Roskomnadzor blocked access to GitHub in December 2014 after the site hosted pages about suicide. More text.",
                 "https://b.example/gone": "An unrelated page with different words entirely."}
        def fetch_text(url, focus=""):
            return {"status": "completed", "excerpt": pages.get(url, "")}
        def fetch_json(url):
            self.assertEqual(url, "https://two.example/backrooms/findings.json")
            return PEER_FEED
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "findings.jsonl"; state = Path(directory) / "federation.json"
            ledger.write_text(json.dumps({"id": "f-own", "url": "https://devactivity.com/insights/x", "claim": "Different claim",
                                          "quote": "GitHub contributions may not appear unless manually rebuilt by GitHub Support", "status": "unreviewed"}) + "\n")
            peers = [{"name": "two", "url": "https://two.example/backrooms"}]
            summary = federation.federate(300, peers, fetch_json, fetch_text, ledger_path=ledger, state_path=state)
            self.assertEqual([row["agent"] for row in summary["imported"]], ["peer:two"])
            row = summary["imported"][0]
            self.assertEqual((row["origin"], row["peer"]["finding_id"], row["quote_match"], row["status"]), ("federated", "p-1", "verified-by-refetch", "unreviewed"))
            self.assertEqual(len(row["content_hash"]), 64)
            self.assertNotEqual(row["content_hash"], "peerhash1")  # this world's own hash of its own fetch
            self.assertEqual(summary["skipped"]["quoted passage not found at the source"], 1)
            self.assertEqual(summary["events"][0]["kind"], "federation-import")
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            again = federation.federate(301, peers, fetch_json, fetch_text, ledger_path=ledger, state_path=state)
            self.assertEqual((again["imported"], len(ledger.read_text().splitlines())), ([], 2))
            saved = json.loads(state.read_text())
            self.assertEqual((saved["peers"]["two"]["imported"], saved["peers"]["two"]["last_status"]), (1, "ok"))
            view = federation.public_view(saved, peers, rows, [{"id": "pair-x", "relation": "supports", "cross_world": True, "domains": ["meduza.io", "techcrunch.com"]}], site_url="https://me.example")
            self.assertEqual((view["imported"], view["cross_world_pairs"], view["peers"][0]["imported"]), (1, 1, 1))
            self.assertNotIn("seen", view["peers"][0])
            report = federation.check("https://two.example/backrooms", fetch_json, fetch_text, own_rows=rows, verify_limit=5)
            self.assertEqual((report["records"], report["eligible"], report["verified"]), (4, 1, 0))  # p-1 is held now; p-5 fails to verify
            self.assertEqual(report["skipped"]["already on this world's ledger"], 1)
            fresh = federation.check("https://two.example/backrooms", fetch_json, fetch_text, own_rows=[], verify_limit=5)
            self.assertEqual((fresh["eligible"], fresh["verified"]), (3, 1))
        self.assertEqual(federation._norm("Roskomnadzor[12] blocked GitHub,[3] in 2014."), "roskomnadzor blocked github in 2014")

    def test_a_pair_with_a_peer_finding_is_cross_world(self):
        from scripts.corroboration import make_record
        ours = {"id": "f-a", "url": "https://techcrunch.com/x", "claim": "Roskomnadzor blocked GitHub in December 2014.", "topic": "t"}
        theirs = {"id": "f-b", "url": "https://meduza.io/y", "claim": "Roskomnadzor blocked GitHub in December 2014.", "topic": "t", "peer": {"name": "two"}}
        self.assertTrue(make_record(ours, theirs, "pair-1", "supports", "same", 300, shared_claim="Roskomnadzor blocked GitHub in December 2014")["cross_world"])
        self.assertFalse(make_record(ours, {**theirs, "peer": None}, "pair-2", "supports", "same", 300)["cross_world"])


if __name__ == "__main__":
    unittest.main()
