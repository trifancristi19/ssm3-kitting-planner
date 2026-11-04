"""Guards the Study 1 prompts.

The 353 runs of Study 1 used exactly these prompts. If a prompt changes, the old
results can no longer be reproduced, so a change must be a new prompt version
with its own task, never an edit of an old one.
"""

import hashlib

from study1.tasks import TASKS

PROMPT_SHA256 = {
    "T1": "e74026b78a1bb2a2053d388f39edb123182f67892d773567b597bbffdc328764",
    "T2": "d0abb36a3ec7bfee0fe4be0f5a5b1cd44a9853644710c2a70ee34b08e444a2ab",
    "T3": "6d2bdbc4f14dee7495f5d2b504066ba414740613a3b36ba46426d540713d1be1",
    "T4": "244eb334c72bf34931d586f75db3ad97348cac6920e819e3ecc26c38735c6349",
    "T5": "97ff697177a85b86a40f7711b1b84719f00f04bd904ad0f59a60258cc0c098a5",
    "T6": "a41d4ded753fcceaae347d4a81a73e86fdafa9ad90b18cfa19a78b87bd02064a",
    "T7": "b892101b9a44ad7046c8069a6006d60b8a4e14e7e2329a050ee433667171f39f",
    "T8": "b7e6079cb84f4ad6a7db718e5ca255870c1e2f4065e50b9b14e414400ffcc7a8",
    "T9": "ea304cc71fad5f7b248a9645d5f91d725e909e65624785457bb7e7dd264c161e",
    "T10": "d21ff81b14e0360e21c11e17ab9bf41c57feab69fff7987355db4cf7449abfd0",
    "T11": "032b5e4a5c25cf4f805d349dd9df61f8fdf9177de1e7ee8260b8927aa8e42915",
    "T12": "82f64d27f07d6c69c76306ba137d453898266086a75247abf8f7baf567afbb9f",
    "T13": "3dcdd52ad98e6b5401f1e5e6f182f4e22d6fda864ee1cce905f95bd725adb603",
    "T14": "00967629e00e03650c78289b81f8fae5f0e590bb8c6d5fcc0649ce2a84b665ce",
    "T15": "330a37da4bedd21af9ccc1f7e13b11596a38ef401c13ab8cd3bc8ad54db888be",
    "T16": "0c622be7d343bb85506566d107ce0eb0c8f40878d07ba0a744aa7ebe004361ec",
}


def test_prompts_are_unchanged():
    current = {t: hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest() for t, task in TASKS.items()}
    assert current == PROMPT_SHA256
