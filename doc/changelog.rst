Changelog
=========

Version 0.2
-----------

General updates
...............

- add support for Python 3.8
- make ``libgsl`` dependency optional

:mod:`nd.classify`
..................

- removed redundant method :func:`nd.classify.cluster()`, as same
  functionality can be achieved using :class:`nd.classify.Classifier`

:mod:`nd.tiling`
................

- added :func:`nd.tiling.debuffer()` to automatically remove buffer from
  tiled datasets


:mod:`nd.utils`
...............

- added :func:`nd.utils.apply()` to apply functions with specified signature to arbitrary subsets of dataset dimensions


:mod:`nd.visualize`
...................

- added :func:`nd.visualize.plot_map()` to plot the geometry of a dataset
  on a map

- added :func:`nd.visualize.gridlines_with_labels()` to add perfectly aligned
  tick labels around a map with gridlines

