# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import glob
from operator import attrgetter
import inspect
import subprocess


try:
    import nd
except ImportError:
    nd_path = os.path.abspath('..')
else:
    nd_path = os.path.abspath(
        os.path.join(os.path.dirname(nd.__file__), '..')
    )
sys.path.insert(0, nd_path)

# -- Project information -----------------------------------------------------

project = 'nd'
copyright = '2018, Johannes Hansen'
author = 'Johannes Hansen'

# The short X.Y version
version = ''
# The full version, including alpha/beta/rc tags
release = ''


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    # 'sphinxcontrib.apidoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.autodoc',
    'sphinx.ext.linkcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.coverage',
    'sphinx.ext.mathjax',
    'sphinx.ext.githubpages',
    'IPython.sphinxext.ipython_console_highlighting',
    'IPython.sphinxext.ipython_directive'
]

# apidoc configuration
# apidoc_module_dir = '../nd'
# apidoc_output_dir = 'api'
# apidoc_excluded_paths = ['**/tests', 'test_*', '**/test_*',
#                          '**/*.pyx', '**/*.pxd']
# apidoc_separate_modules = False
# apidoc_toc_file = False

# Mock imports for autodoc
autodoc_mock_imports = ['sklearn']
autodoc_warningiserror = False

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# Ipython option
ipython_savefig_dir = 'images'

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = None


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {
    # 'logo_only': True,
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

html_favicon = 'logos/favicon.ico'
# html_logo = 'logos/nd_text.png'


# Determine github source links:
def linkcode_resolve(domain, info):
    url = u'https://github.com/jnhansen/nd/tree/{revision}/'\
          '{package}/{path}#L{lineno}'

    # Determined git revision
    try:
        revision = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD']
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return None

    revision = revision.decode('utf-8')

    package = 'nd'
    if domain not in ('py', 'pyx'):
        return
    if not info.get('module') or not info.get('fullname'):
        return

    class_name = info['fullname'].split('.')[0]
    module = __import__(info['module'], fromlist=[class_name])
    obj = attrgetter(info['fullname'])(module)

    try:
        path = inspect.getsourcefile(obj)
    except Exception:
        path = None
    if not path:
        try:
            path = inspect.getsourcefile(sys.modules[obj.__module__])
        except Exception:
            path = None
    if not path:
        return

    path = os.path.relpath(path,
                           start=os.path.dirname(__import__(package).__file__))
    try:
        lineno = inspect.getsourcelines(obj)[1]
    except Exception:
        lineno = ''
    return url.format(revision=revision, package=package,
                      path=path, lineno=lineno)


# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}


# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = 'nddoc'


# -- Options for LaTeX output ------------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',

    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',

    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',

    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'nd.tex', 'nd Documentation',
     'Johannes Hansen', 'manual'),
]


# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    (master_doc, 'nd', 'nd Documentation',
     [author], 1)
]


# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'nd', 'nd Documentation',
     author, 'nd', 'Geospatial data processing in Python',
     'Miscellaneous'),
]


# -- Options for Epub output -------------------------------------------------

# Bibliographic Dublin Core info.
epub_title = project

# The unique identifier of the text. This can be a ISBN number
# or the project homepage.
#
# epub_identifier = ''

# A unique identification for the text.
#
# epub_uid = ''

# A list of files that should not be packed into the epub file.
epub_exclude_files = ['search.html']


# -- Extension configuration -------------------------------------------------
autosummary_generate = glob.glob("api/*.rst")
