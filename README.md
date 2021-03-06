# dataextractors

A collection of functions to extract pixels and metadata using geojson and georeferenced imagery.

## Installation/Usage

In a virtualenv or conda virtual environment:

```bash
pip install dataextractors
```

A conda environment is preferred because the installation of gdal is straightforward:

```bash
conda create -n myenv -c conda-forge gdal
source activate myenv
```

## Development

Clone the repo:

```bash
git clone https://github.com/digitalglobe/dataextractors
cd dataextractors
```

Install the requirements:

```bash
pip install -r requirements.txt
```

Please follow [this python style guide](https://google.github.io/styleguide/pyguide.html). 80-90 columns is fine.


### Create a new version

To create a new version:

```bash
bumpversion ( major | minor | patch )
git push --tags
```

Then upload to pypi.
