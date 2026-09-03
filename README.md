[![Tests](https://github.com/DataShades/ckanext-dataset-merge/actions/workflows/test.yml/badge.svg)](https://github.com/DataShades/ckanext-dataset-merge/actions/workflows/test.yml)

# ckanext-dataset-merge

A guided workflow for merging two datasets of the same type into one.

One dataset (**A**, the *base*) survives the merge — it keeps its identity (ID),
URL, revision history and, when `scheming_dynamic` is active, its schema-version
pin. Selected metadata fields and resources from a second dataset (**B**, the
*source*) are folded into A, and B is then soft-deleted.

## Features

- **Start-merge picker** – an "Merge datasets" action on the dataset page and the
  dataset search page opens a modal that searches the datasets you are allowed to
  edit and checks whether the pair can be merged.
- **Compatibility checks** – both datasets must be the same type. With
  `scheming_dynamic` enabled and either dataset pinned to a schema version, they
  must share the *exact* pinned schema type and version; otherwise the user is
  told to migrate first.
- **Side-by-side review page** – every schema field is shown for both datasets
  and classified as *same*, *only on A*, *only on B*, *empty* or *conflict*.
  Non-conflicting values are carried over automatically; conflicts get a
  radio choice (Dataset A is the default).
- **Combine multi-value fields** – for set-valued fields such as **tags** a
  conflict also offers a *Both datasets* option that keeps the union of the two
  values, and that union is pre-selected.
- **Preview + confirm** – a modal shows the final metadata and the resource list
  before anything is written.
- **Safe apply** – A is updated first and B is only soft-deleted afterwards. If
  the cleanup step fails, A stays merged and a retry page lets you finish
  deleting B without re-running the merge.

### Actions

| Action | Description |
| --- | --- |
| `merge_compatibility` | Report whether two datasets are eligible to be merged. |
| `merge_metadata_comparison` | Field-by-field comparison for the review form. |
| `merge_resolve_decisions` | Resolve submitted choices without changing anything. |
| `merge_apply_to_base` | Apply the chosen content to A (leaves B untouched). |
| `merge_cleanup_source` | Soft-delete B after A has been updated. |

## Requirements

**[ckanext-scheming](https://github.com/ckan/ckanext-scheming)** is required — the
field list for the review page comes from the dataset's scheming schema, so the
`scheming_datasets` plugin must be enabled.

**`scheming_dynamic` is optional.** It is not part of upstream ckanext-scheming;
it ships in the [DataShades
fork](https://github.com/DataShades/ckanext-scheming/tree/dynamic-schemas). When
its plugin is loaded the merge additionally requires the two datasets to share an
*exact* pinned schema type **and** version; without it, eligibility is just a
dataset-type match. The plugin detects this at runtime
(`p.plugin_loaded("scheming_dynamic")`) — nothing to configure.

Compatibility with core CKAN versions:

| CKAN version | Compatible? |
| ------------ | ----------- |
| 2.10 and earlier | no (needs `h.csrf_input`, CKAN 2.11+) |
| 2.11         | yes |
| 2.12         | yes |

## Installation

1. Activate your CKAN virtual environment, for example:

       . /usr/lib/ckan/default/bin/activate

2. Install the extension (this pulls in `ckanext-scheming`):

       pip install ckanext-dataset-merge

   Only if you want the `scheming_dynamic` behaviour, install the DataShades
   fork instead of upstream ckanext-scheming:

       pip install "ckanext-scheming[dynamic] @ git+https://github.com/DataShades/ckanext-scheming.git@dynamic-schemas"

3. Add the plugins to the `ckan.plugins` setting in your CKAN config file, with
   `dataset_merge` after `scheming_datasets`:

       ckan.plugins = ... scheming_datasets dataset_merge
       # or, with dynamic schemas:
       ckan.plugins = ... scheming_datasets scheming_dynamic dataset_merge

4. If you enabled `scheming_dynamic` for the first time, apply its migrations:

       ckan db upgrade -p scheming_dynamic

5. Restart CKAN.

## Config settings

None.

## Developer installation

    git clone https://github.com/DataShades/ckanext-dataset-merge.git
    cd ckanext-dataset-merge
    # the test suite exercises the dynamic-schema path, so use the fork here
    pip install "ckanext-scheming[dynamic] @ git+https://github.com/DataShades/ckanext-scheming.git@dynamic-schemas"
    pip install ckanext-xloader
    pip install -e '.[dev]'

The front-end assets (`ckanext/dataset_merge/assets/`) are built from SCSS with
gulp — run `npm install && npm run build` (or `npx gulp watch` while working)
after changing anything under `assets/scss/`.

## Tests

    pytest --ckan-ini=test.ini

The suite needs Postgres, Solr and Redis (as configured in `test.ini`). Most
tests cover the `scheming_dynamic` behaviour, so they need the DataShades
ckanext-scheming fork and `ckanext-xloader` on the path — see the developer
installation above and `.github/workflows/test.yml`.

## Releasing a new version

1. Bump `version` in `pyproject.toml` (see [PEP 440](https://peps.python.org/pep-0440/#public-version-identifiers)).
2. `pip install --upgrade build twine`
3. `python -m build && twine check dist/*`
4. `twine upload dist/*`
5. Commit, push, then tag the release:

       git tag v$(python -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
       git push --tags

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
