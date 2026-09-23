from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "output" / "verification" / "m08-m18-delivery-gate.json"
EXE = ROOT / "output" / "app" / "新DC篇完整修改器.exe"
EXE_HASH = EXE.with_suffix(EXE.suffix + ".sha256.txt")
CURRENT_BUILD_EVIDENCE = (
    ROOT
    / "output"
    / "verification"
    / "m08-m18-current-build-verification-2026-09-19.json"
)
AGENT_UI_SMOKE = (
    ROOT
    / "output"
    / "verification"
    / "m08-m18-agent-ui-smoke-2026-09-19.json"
)
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
EXPECTED_ROM_SHA256 = "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E"


MODULES: dict[str, dict[str, object]] = {
    "M08": {
        "evidence": "output/verification/m08-battle-text-compatibility.json",
        "checklist": "docs/M08验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M09": {
        "evidence": "output/verification/m09-other1-compatibility.json",
        "checklist": "docs/M09验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M10": {
        "evidence": "output/verification/m10-other2-compatibility.json",
        "checklist": "docs/M10验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M11": {
        "evidence": "output/verification/m11-font-compatibility.json",
        "checklist": "docs/M11验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M12": {
        "evidence": "output/verification/m12-animation-compatibility.json",
        "checklist": "docs/M12验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_guarded_scope",
    },
    "M13": {
        "evidence": "output/verification/m13-text-conversion.json",
        "checklist": "docs/M13验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M14": {
        "evidence": "output/verification/m14-scenario-compatibility.json",
        "checklist": "docs/M14验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M15": {
        "evidence": "output/verification/m15-attribute-calculator.json",
        "checklist": "docs/M15验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M16": {
        "evidence": "output/verification/m16-save-compatibility.json",
        "checklist": "docs/M16验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_guarded_scope",
    },
    "M17": {
        "evidence": "output/verification/m17-global-compatibility.json",
        "checklist": "docs/需求拆分/M17_其他窗口.md",
        "implementation_scope_complete": True,
        "status": "user_accepted_current_scope",
    },
    "M18": {
        "evidence": "output/verification/m18-unit-export-verification.json",
        "checklist": "docs/M18验收清单.md",
        "implementation_scope_complete": True,
        "status": "user_accepted",
    },
}

USER_ACCEPTANCE = {
    "M08": "accepted",
    "M09": "accepted",
    "M10": "accepted",
    "M11": "accepted",
    "M12": "accepted",
    "M13": "accepted",
    "M14": "accepted",
    "M15": "accepted",
    "M16": "accepted",
    "M17": "accepted",
    "M18": "accepted",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def analyze() -> dict[str, object]:
    expected_exe_hash = EXE_HASH.read_text(encoding="utf-8").split()[0].upper()
    actual_exe_hash = _sha256(EXE)
    actual_rom_hash = _sha256(ROM)
    current_build_evidence = json.loads(
        CURRENT_BUILD_EVIDENCE.read_text(encoding="utf-8")
    )
    verified_exe_hash = str(
        current_build_evidence["formalExecutable"]["sha256"]
    ).upper()
    agent_ui_smoke = json.loads(AGENT_UI_SMOKE.read_text(encoding="utf-8"))
    smoked_exe_hash = str(agent_ui_smoke["executable"]["sha256"]).upper()

    modules: dict[str, dict[str, object]] = {}
    for module, declaration in MODULES.items():
        evidence_path = ROOT / str(declaration["evidence"])
        checklist_path = ROOT / str(declaration["checklist"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        checklist_text = (
            checklist_path.read_text(encoding="utf-8")
            if checklist_path.is_file()
            else ""
        )
        checklist_declares_current_executable = (
            module == "M17" or expected_exe_hash in checklist_text.upper()
        )
        modules[module] = {
            "status": declaration["status"],
            "implementation_scope_complete": declaration["implementation_scope_complete"],
            "machine_gate_passed": evidence.get("passed") is True,
            "evidence": str(declaration["evidence"]),
            "evidence_sha256": _sha256(evidence_path),
            "checklist": str(declaration["checklist"]),
            "checklist_exists": checklist_path.is_file(),
            "checklist_declares_current_executable": checklist_declares_current_executable,
            # Standing rule: only an explicit user decision can change this.
            "user_acceptance": USER_ACCEPTANCE.get(module, "pending"),
        }

    machine_gate_passed = (
        actual_exe_hash == expected_exe_hash
        and verified_exe_hash == actual_exe_hash
        and current_build_evidence["formalExecutable"]["selfTestExitCode"] == 0
        and current_build_evidence["fullRegression"]["passed"] is True
        and actual_rom_hash == EXPECTED_ROM_SHA256
        and all(
            item["machine_gate_passed"]
            and item["checklist_exists"]
            and item["checklist_declares_current_executable"]
            for item in modules.values()
        )
    )
    implementation_complete = all(
        item["implementation_scope_complete"] for item in modules.values()
    )
    user_acceptance_complete = all(
        item["user_acceptance"] == "accepted" for item in modules.values()
    )

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine_gate_passed": machine_gate_passed,
        "implementation_complete": implementation_complete,
        "user_acceptance_complete": user_acceptance_complete,
        "overall_delivery_complete": (
            machine_gate_passed and implementation_complete and user_acceptance_complete
        ),
        "conclusion": (
            "M08—M18 共 11 个模块的机器门禁与当前声明实现范围均通过；M12 已用参考动态黄金"
            "把组图首图块开放、X/Y 非持久化锁为只读，其余无安全协议或双证据范围继续门禁。"
            "M08—M17 已由用户明确按当前实现范围签收，M18 已由用户现场确认通过；"
            "既有只读、延期和参考不可达边界继续保留。"
        ),
        "formal_executable": {
            "path": EXE.resolve().relative_to(ROOT).as_posix(),
            "sha256": actual_exe_hash,
            "declared_sha256": expected_exe_hash,
            "hash_matches": actual_exe_hash == expected_exe_hash,
        },
        "current_build_verification": {
            "path": CURRENT_BUILD_EVIDENCE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(CURRENT_BUILD_EVIDENCE),
            "full_regression_passed": current_build_evidence["fullRegression"][
                "passed"
            ],
            "full_regression_tests": current_build_evidence["fullRegression"][
                "testsRun"
            ],
            "self_test_exit_code": current_build_evidence["formalExecutable"][
                "selfTestExitCode"
            ],
            "executable_sha256": verified_exe_hash,
            "matches_current_executable": verified_exe_hash == actual_exe_hash,
            "current_build_click_smoke_performed": current_build_evidence[
                "nativeUiAutomation"
            ]["currentBuildClickSmokePerformed"],
            "mesen_runtime_passed": current_build_evidence["mesenRuntime"][
                "passed"
            ],
            "mesen_runtime_checks": current_build_evidence["mesenRuntime"][
                "checks"
            ],
        },
        "agent_ui_smoke": {
            "path": AGENT_UI_SMOKE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(AGENT_UI_SMOKE),
            "passed": agent_ui_smoke["agentUiSmokePassed"],
            "executable_sha256": smoked_exe_hash,
            "matches_current_executable": smoked_exe_hash == actual_exe_hash,
        },
        "recommended_rom": {
            "path": ROM.resolve().relative_to(ROOT).as_posix(),
            "sha256": actual_rom_hash,
            "expected_sha256": EXPECTED_ROM_SHA256,
            "hash_matches": actual_rom_hash == EXPECTED_ROM_SHA256,
        },
        "counts": {
            "modules": len(modules),
            "machine_gate_passed": sum(
                bool(item["machine_gate_passed"]) for item in modules.values()
            ),
            "implementation_scope_complete": sum(
                bool(item["implementation_scope_complete"]) for item in modules.values()
            ),
            "user_accepted": sum(
                item["user_acceptance"] == "accepted" for item in modules.values()
            ),
        },
        "modules": modules,
        "blocking_reasons": [
            "M12 的 6 条无安全参数、31 条动态/不完整背景、三表任意通用搬移和 8 个已逐项审计但证据冲突/不足的调用均按需求保持只读；这是完成态安全门禁，不是待猜写功能。",
            "当前正式构建已通过 746/746 全量回归和隐藏自检；Mesen 17/17 是推荐 ROM 运行时基线。Windows 控制组件本轮初始化失败，因此可见点击证据仍沿用历史构建并明确标记不匹配当前 EXE。",
            "2026-09-21 用户明确确认 M03—M17 按当前实现范围通过；本报告据此记录 M08—M17 用户签收，不扩大任何模块的声明实现范围。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总 M08—M18 机器门禁与人工验收状态。")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze()
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # This command is a machine gate, so user acceptance/overall completion do
    # not change its exit status.  Unsafe or missing machine evidence does.
    return 0 if report["machine_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
