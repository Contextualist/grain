.. Grain documentation master file, created by
   sphinx-quickstart on Wed May 20 11:23:00 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Grain's documentation!
=================================

Grain parallelizes your workload across supercomputing clusters, just like
Dask, Ray, etc.. Unlike the existing solutions, Grain focuses on one scenario:
running external calculations (i.e. binary executables) with defined resource
constraints.

Release notes: https://github.iu.edu/IyengarLab/grain/releases (so far,
commit messages provide better information for the features and fixes)


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   tutorial_delayed.rst
   api_delayed.rst
   resource.rst
   util.rst

Work in progress:

* Resource: a language for coordination
* Bridge protocol: universal connection
* FAQ
* Low-level API reference

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
