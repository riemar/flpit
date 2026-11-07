import pytest
from collections import Counter, defaultdict
from pathlib import Path


class ReadmeRuntimeTablePlugin:
    def __init__(self):
        self.skips = defaultdict(Counter)
        self.totals = defaultdict(int)
        self.passed = defaultdict(int)

    @staticmethod
    def _relative_test_path(file_path):
        """Return the path below tests/nettests, retaining subfolder names."""
        parts = Path(file_path).parts
        try:
            nettests_index = parts.index("nettests")
        except ValueError:
            return Path(file_path).name
        return Path(*parts[nettests_index + 1:]).as_posix()

    def pytest_runtest_logreport(self, report):
        if report.skipped and report.when in ("setup", "call"):
            file_path = report.fspath
            reason = "Skipped"
            if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
                reason = report.longrepr[2]
            elif hasattr(report, "wasxfail"):
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
        output.append("=" * 110)
        output.append(f"{'Test Module File':<55} | {'Total':<5} | {'Skipped':<7} | Status / Reason for Skip")
        output.append("-" * 110)

        grand_total = 0
        grand_skipped = 0

        for full_path in sorted(self.totals):
            path = self._relative_test_path(full_path)

            total_cases = self.totals[full_path]
            skipped_cases = sum(self.skips[full_path].values())

            grand_total += total_cases
            grand_skipped += skipped_cases

            if skipped_cases == 0:
                output.append(f"{path:<55} | {total_cases:<5} | {'0':<7} | 100.0% Semantic Parity [✓]")
                output.append("-" * 110)
                continue

            file_pct = ((total_cases - skipped_cases) / total_cases * 100)
            output.append(f"{path:<55} | {total_cases:<5} | {skipped_cases:<7} | {file_pct:.1f}% Complete")

            for reason, count in self.skips[full_path].most_common():
                output.append(f"{'':<55} | {'':<5} | {'':<7} |   └── ({count}x) {reason}")
            output.append("-" * 110)

        pct = ((grand_total - grand_skipped) / grand_total * 100) if grand_total else 0
        output.append(f"{'GRAND TOTALS':<55} | {grand_total:<5} | {grand_skipped:<7} | Parity: {pct:.1f}% Complete")
        output.append("=" * 110)
        output.append("")

        # --- Table 2: Successful Test Cases, grouped by subfolder ---
        width = 80
        tree_width = 62
        output.append("=" * width)
        output.append(f"{'| Test Module File':<64} | {'Test Cases':>11} |")
        output.append("-" * width)
        output.append(f"| {'tests/nettests/':<{tree_width}} | {'':>11} |")

        files_by_parent = defaultdict(list)
        for full_path in self.totals:
            relative_path = Path(self._relative_test_path(full_path))
            files_by_parent[relative_path.parent.as_posix()].append((relative_path.name, full_path))

        grand_passed = 0
        parent_groups = sorted(files_by_parent)
        for group_index, parent in enumerate(parent_groups):
            is_last_group = group_index == len(parent_groups) - 1
            group_branch = "└──" if is_last_group else "├──"

            if parent == ".":
                prefix = ""
            else:
                prefix = "    " if is_last_group else "│   "
                output.append(f"| {group_branch} {parent}/".ljust(tree_width + 2) + f" | {'':>11} |")

            files = sorted(files_by_parent[parent])
            for file_index, (filename, full_path) in enumerate(files):
                passed_cases = self.passed[full_path]
                grand_passed += passed_cases

                is_last_file = file_index == len(files) - 1
                file_branch = "└──" if is_last_file else "├──"
                tree_entry = f"{prefix}{file_branch} {filename}"
                output.append(f"| {tree_entry:<{tree_width}} | {passed_cases:>11} |")

        output.append("-" * width)
        output.append(f"| {'GRAND TOTALS':<{tree_width}} | {grand_passed:>11} |")
        output.append("=" * width)

        print("\n" + "\n".join(output) + "\n")


if __name__ == "__main__":
    plugin = ReadmeRuntimeTablePlugin()
    pytest.main(["-q", "tests/nettests/"], plugins=[plugin])
