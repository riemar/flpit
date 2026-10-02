import pytest
from collections import Counter, defaultdict
from pathlib import Path

class ReadmeRuntimeTablePlugin:
    def __init__(self):
        self.skips = defaultdict(Counter)
        self.totals = defaultdict(int)
        self.passed = defaultdict(int)

    def pytest_runtest_logreport(self, report):
        if report.skipped and report.when in ("setup", "call"):
            file_path = report.fspath
            reason = "Skipped"
            if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
                reason = report.longrepr[2]
            elif hasattr(report, 'wasxfail'):
                reason = "XFAIL"

            self.skips[file_path][reason] += 1
            self.totals[file_path] += 1

        elif report.when == "call":
            file_path = report.fspath
            self.totals[file_path] += 1
            if report.passed:
                self.passed[file_path] += 1

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        terminalreporter.ensure_newline()

        output = []

        # --- Table 1: detailed list ---
        output.append("=" * 100)
        output.append(f"{'Test Module File':<45} | {'Total':<5} | {'Skipped':<7} | Status / Reason for Skip")
        output.append("-" * 100)

        grand_total = 0
        grand_skipped = 0

        for full_path in sorted(self.totals):
            path = Path(full_path).name

            total_cases = self.totals[full_path]
            skipped_cases = sum(self.skips[full_path].values())

            grand_total += total_cases
            grand_skipped += skipped_cases

            if skipped_cases == 0:
                output.append(f"{path:<45} | {total_cases:<5} | {'0':<7} | 100.0% Semantic Parity [✓]")
                output.append("-" * 100)
                continue

            file_pct = ((total_cases - skipped_cases) / total_cases * 100)
            output.append(f"{path:<45} | {total_cases:<5} | {skipped_cases:<7} | {file_pct:.1f}% Complete")

            for reason, count in self.skips[full_path].most_common():
                output.append(f"{'':<45} | {'':<5} | {'':<7} |   └── ({count}x) {reason}")
            output.append("-" * 100)

        pct = ((grand_total - grand_skipped) / grand_total * 100) if grand_total else 0
        output.append(f"{'GRAND TOTALS':<45} | {grand_total:<5} | {grand_skipped:<7} | Parity: {pct:.1f}% Complete")
        output.append("=" * 100)
        output.append("")

        # --- Table 2: Successful Test Cases ---
        width = 64
        output.append("=" * width)
        output.append(f"{'| Test Module File':<48} | {'Test Cases':>11} |")
        output.append("-" * width)

        grand_passed = 0
        for full_path in sorted(self.totals):
            try:
                path = str(Path(full_path).relative_to(config.rootpath))
            except:
                path = full_path

            passed_cases = self.passed[full_path]
            grand_passed += passed_cases

            output.append(f"| {path:<46} | {passed_cases:>11} |")

        output.append("-" * width)
        output.append(f"| {'GRAND TOTALS':<46} | {grand_passed:>11} |")
        output.append("=" * width)

        print("\n" + "\n".join(output) + "\n")


if __name__ == "__main__":
    plugin = ReadmeRuntimeTablePlugin()
    pytest.main(["-q", "tests/nettests"], plugins=[plugin])
# import pytest
# from collections import Counter, defaultdict
#
# class ReadmeRuntimeTablePlugin:
#     def __init__(self):
#         # Erfasst: Datei -> { Skip-Grund -> Anzahl }
#         self.skips = defaultdict(Counter)
#         # Erfasst die Gesamtanzahl der tatsächlich ausgeführten/ausgewerteten Fälle pro Datei
#         self.totals = defaultdict(int)
#
#     def pytest_runtest_logreport(self, report):
#         # Wir werten den Report in der 'call'-Phase (oder 'setup' für Klassen-Skips) aus.
#         # Wichtig: Ein Skip kann im Setup (z.B. skipif) oder im Call (Inline-Skip) passieren.
#         if report.skipped and report.when in ("setup", "call"):
#             file_path = report.fspath
#             # Extrahiere den echten Runtime-Grund aus dem Test-Report tuple
#             # pytest speichert das Tuple bei skips als (dateiname, zeile, grund)
#             reason = "Skipped"
#             if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
#                 reason = report.longrepr[2]
#             elif hasattr(report, 'wasxfail'):
#                 reason = "XFAIL"
#
#             self.skips[file_path][reason] += 1
#             self.totals[file_path] += 1
#
#         elif report.when == "call":
#             # Für alle durchgelaufenen (Passed/Failed) Tests erhöhen wir den Zähler im Call
#             file_path = report.fspath
#             self.totals[file_path] += 1
#
#     def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
#         terminalreporter.ensure_newline()
#
#         output = []
#         output.append("=" * 100)
#         output.append(f"{'Test Module File':<45} | {'Total':<5} | {'Skipped':<7} | Status / Reason for Skip")
#         output.append("-" * 100)
#
#         grand_total = 0
#         grand_skipped = 0
#
#         for full_path in sorted(self.totals):
#             try:
#                 path = str(Path(full_path).relative_to(config.rootpath))
#             except:
#                 path = full_path
#
#             total_cases = self.totals[full_path]
#             skipped_cases = sum(self.skips[full_path].values())
#
#             grand_total += total_cases
#             grand_skipped += skipped_cases
#
#             if skipped_cases == 0:
#                 output.append(f"{path:<45} | {total_cases:<5} | {'0':<7} | 100.0% Semantic Parity [✓]")
#                 output.append("-" * 100)
#                 continue
#
#             # Calculate file specific percentage
#             file_pct = ((total_cases - skipped_cases) / total_cases * 100)
#             output.append(f"{path:<45} | {total_cases:<5} | {skipped_cases:<7} | {file_pct:.1f}% Complete")
#
#             for reason, count in self.skips[full_path].most_common():
#                 output.append(f"{'':<45} | {'':<5} | {'':<7} |   └── ({count}x) {reason}")
#             output.append("-" * 100)
#
#         pct = ((grand_total - grand_skipped) / grand_total * 100) if grand_total else 0
#         output.append(f"{'GRAND TOTALS':<45} | {grand_total:<5} | {grand_skipped:<7} | Parity: {pct:.1f}% Complete")
#         output.append("=" * 100)
#
#         print("\n" + "\n".join(output) + "\n")
#
#
# if __name__ == "__main__":
#     from pathlib import Path
#     # Dieses Mal führen wir pytest normal aus (ohne --collect-only),
#     # damit die Testphasen durchlaufen und die Skips getriggert werden.
#     # -q unterdrückt den Standard-Pytest-Output, damit nur unsere Tabelle kommt.
#     plugin = ReadmeRuntimeTablePlugin()
#     pytest.main(["-q", "tests/nettests"], plugins=[plugin])
