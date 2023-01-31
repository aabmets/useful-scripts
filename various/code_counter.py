from dotmap import DotMap
from pathlib import Path


# -------------------------------------------------------------------------------- #
folders = ["rik_app", "tests", "scripts"]  # must be top-level


# -------------------------------------------------------------------------------- #
def print_results(results, folder_name=None):
    print('')
    if folder_name:
        print(f'Folder "{folder_name}" results:')
        print('-' * 25)
    else:
        print('\nTOTAL RESULTS:')
        print('=' * 25)
    print('Total lines:     ' + str(results.total_lines))
    print('Code lines:      ' + str(results.code_lines))
    print('Comment lines:   ' + str(results.comment_lines))
    print('Blank lines:     ' + str(results.blank_lines))
    if not folder_name:
        print()


# -------------------------------------------------------------------------------- #
def begin_walk(path) -> DotMap:
    data = DotMap()
    for item in path.iterdir():
        if item.is_dir():
            results = begin_walk(item)
            for k, v in results.items():
                data[k] += v
        elif item.is_file() and item.suffix == '.py':
            with open(item, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    data.total_lines += 1
                    if line == '':
                        data.blank_lines += 1
                    elif line.startswith("#"):
                        data.comment_lines += 1
                    else:
                        data.code_lines += 1
    return data


# -------------------------------------------------------------------------------- #
def find_pyproject_toml(path):
    totals = DotMap()
    if (path / "pyproject.toml").is_file():
        for folder in folders:
            results = begin_walk(path / folder)
            for k, v in results.items():
                totals[k] += v
            print_results(results, folder)
        print_results(totals)
    elif path.parent != path:
        find_pyproject_toml(path.parent)
    else:
        print("Unable to find pyproject.toml file! ", end='')
        print("This script should be executed inside a Python project folder.")


# -------------------------------------------------------------------------------- #
if __name__ == "__main__":
    start_path = Path(__file__).resolve().parent
    find_pyproject_toml(start_path)
