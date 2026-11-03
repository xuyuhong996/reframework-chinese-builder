"""验证派发重试与幂等，不访问真实服务。"""

import copy
import os
import unittest
from unittest.mock import Mock, call, patch

from scripts import nexus_dispatch as dispatch

TAG = "build-123456abcdef"
RELEASE = {"id": 1, "tag_name": TAG, "body": "保留的发布说明\n" + dispatch.PENDING_MARKER}


class NexusDispatchTests(unittest.TestCase):
    def clients(self, run=None):
        public = Mock()
        public.request.return_value = copy.deepcopy(RELEASE)
        publisher = Mock()
        publisher.request.return_value = {"workflow_runs": [] if run is None else [run]}
        return public, publisher

    def testNewPendingReleaseOnlyPassesTheReleaseTag(self):
        public, publisher = self.clients()
        dispatch.dispatchPending(public, publisher)
        self.assertIn(
            call(
                "actions/workflows/publish-nexus.yml/dispatches",
                "POST",
                {"ref": "main", "inputs": {"release_tag": TAG}},
            ),
            publisher.request.call_args_list,
        )
        body = public.request.call_args.args[-1]["body"]
        self.assertIn("保留的发布说明", body)
        self.assertIn(dispatch.ACCEPTED_MARKER, body)

    def testExistingRunPreventsAnotherDispatchWhenAcknowledgementWasLost(self):
        public, publisher = self.clients({"display_title": f"Nexus {TAG}", "conclusion": "failure"})
        dispatch.dispatchPending(public, publisher)
        self.assertEqual(publisher.request.call_count, 1)
        self.assertEqual(public.request.call_args.args[1], "PATCH")

    def testDispatchFailureKeepsPendingReleaseForTheNextCheck(self):
        public, publisher = self.clients()
        publisher.request.side_effect = [{"workflow_runs": []}, OSError("网络失败")]
        with self.assertRaises(OSError):
            dispatch.dispatchPending(public, publisher)
        self.assertEqual(public.request.call_count, 1)
        publisher.request.side_effect = None
        publisher.request.return_value = {"workflow_runs": []}
        dispatch.dispatchPending(public, publisher)
        self.assertEqual(public.request.call_args.args[1], "PATCH")

    def testHistoricalAndAcknowledgedReleasesAreNotReplayed(self):
        for body in ("历史发布，无派发待办", dispatch.ACCEPTED_MARKER):
            public, publisher = self.clients()
            public.request.return_value["body"] = body
            dispatch.dispatchPending(public, publisher)
            publisher.request.assert_not_called()
            self.assertEqual(public.request.call_count, 1)

    def testMissingTokenDoesNotContactEitherRepository(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(dispatch, "GitHubClient") as client:
            self.assertEqual(dispatch.main(), 0)
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
