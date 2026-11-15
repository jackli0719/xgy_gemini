"""故意让 CI 变红用的探针（临时分支 tmp/ci-red-check 用）。

不是正式测试：它一定会失败，用来验证 GitHub Actions 真的会拦住
失败的提交。验证完就删掉这个分支。
"""


def test_canary_is_red_on_purpose() -> None:
    assert False, "故意失败：验证 CI 门禁会拦住这一条"
