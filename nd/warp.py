import glob
import os
import numpy as np
import xarray as xr
import rasterio.warp
import warnings
from rasterio.coords import BoundingBox
from rasterio.crs import CRS
from rasterio.errors import CRSError
from affine import Affine
from .algorithm import Algorithm, wrap_algorithm
from .io import to_netcdf, open_dataset, disassemble_complex
from .utils import get_vars_for_dims
# skimage only needed for coregistration --> make optional
import skimage


__all__ = ['Reprojection',
           'reproject',
           'Resample',
           'resample',
           'Alignment',
           'align',
           'Coregistration',
           'coregister',
           '_parse_crs',
           'get_crs',
           'get_transform',
           'get_resolution',
           'get_bounds',
           'get_extent',
           'nrows',
           'ncols',
           'get_common_bounds',
           'get_common_extent',
           'get_common_resolution']


def _get_dim_order(ds):
    """
    Return the dimension of dataset `ds` in order.
    """
    # The ordered dictionary is hidden behind two wrappers,
    # need to access the dict behind the Frozen(SortedKeysDict).
    if isinstance(ds, xr.Dataset):
        return list(ds.sizes.mapping.mapping)
    elif isinstance(ds, xr.DataArray):
        return list(ds.sizes.mapping)


def _get_projection_dim_order(ds):
    """
    Return the dimension order required by the projection operations.
    This moves the x and y dimensions to the end.
    """
    dims = _get_dim_order(ds)
    extra_dims = set(dims) - {'y', 'x'}
    ordered_extra_dims = \
        tuple(d for d in dims if d in extra_dims)
    return ordered_extra_dims + ('y', 'x')


def _parse_crs(crs):
    """Parse a coordinate reference system from a variety of representations.

    Parameters
    ----------
    crs : {str, dict, int, CRS}
        Must be either a rasterio CRS object, a proj-string, rasterio supported
        dictionary, WKT string, or EPSG integer.

    Returns
    -------
    rasterio.crs.CRS
        The parsed CRS.

    Raises
    ------
    CRSError
        Raises an error if the input cannot be parsed.
    """

    #
    # NOTE: This doesn't currently throw an error if the EPSG code is invalid.
    #
    parsed = None
    if isinstance(crs, CRS):
        parsed = crs
    elif isinstance(crs, str):
        try:
            # proj-string or wkt
            parsed = CRS.from_string(crs)
        except CRSError:
            # wkt
            parsed = CRS.from_wkt(crs)
    elif isinstance(crs, dict):
        parsed = CRS(crs)
    elif isinstance(crs, int):
        parsed = CRS.from_epsg(crs)

    if parsed is None or not parsed.is_valid:
        raise CRSError('Could not parse CRS: {}'.format(crs))

    return parsed


def get_crs(ds, format='crs'):
    """Extract the Coordinate Reference System from a dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset
    format : str {'crs', 'proj', 'dict', 'wkt'}
        The format in which to return the CRS.

        * 'proj': A proj-string, e.g. ``+init=epsg:4326``

        * 'dict': e.g. ``{'init': 'EPSG:4326'}``

        * 'wkt': e.g. ``GEOGCS["WGS 84", ...]``

    Returns
    -------
    CRS, str, or dict
        The CRS.
    """

    crs = None
    if 'crs' in ds.attrs:
        crs = _parse_crs(ds.attrs['crs'])
    elif 'coordinate_system_string' in ds.attrs:
        crs = _parse_crs(ds.attrs['coordinate_system_string'])
    elif isinstance(ds, xr.Dataset) and 'crs' in ds.data_vars:
        for attr in ds['crs'].attrs:
            try:
                crs = _parse_crs(ds['crs'].attrs[attr])
            except CRSError:
                pass
            else:
                break

    if crs is None:
        return None

    if format == 'crs':
        return crs
    if format == 'proj':
        return crs.to_proj4()
    if format == 'dict':
        return crs.to_dict()
    if format == 'wkt':
        return crs.wkt


def get_transform(ds):
    """Extract the geographic transform from a dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset

    Returns
    -------
    affine.Affine
        The affine transform
    """

    if 'transform' in ds.attrs:
        ds_trans = ds.attrs['transform']
        if isinstance(ds_trans, Affine):
            return ds_trans
        else:
            return Affine(*ds_trans)

    elif isinstance(ds, xr.Dataset) and \
            'crs' in ds.data_vars and 'i2m' in ds.data_vars['crs'].attrs:
        transf_str = ds.data_vars['crs'].attrs['i2m']
        a = list(map(float, transf_str.split(',')))
        return Affine(a[0], a[2], a[4], a[1], a[3], a[5])

    else:
        x = ds.coords['x'].values
        y = ds.coords['y'].values
        resx = (x[-1] - x[0]) / (len(x) - 1)
        resy = (y[-1] - y[0]) / (len(y) - 1)
        xoff = x[0]
        yoff = y[0]
        return Affine(resx, 0, xoff, 0, resy, yoff)


def get_resolution(ds):
    """Extract the resolution of the dataset in projection coordinates.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset

    Returns
    -------
    tuple
        The raster resolution as (x, y)
    """

    if 'x' in ds.coords and 'y' in ds.coords:
        x = ds.coords['x'].values
        y = ds.coords['y'].values
        resx = abs(x[-1] - x[0]) / (len(x) - 1)
        resy = abs(y[-1] - y[0]) / (len(y) - 1)
        return (resx, resy)
    else:
        transform = get_transform(ds)
        if transform is not None:
            return (abs(transform.a), abs(transform.e))
        elif 'res' in ds.attrs:
            return ds.attrs['res']

    return None


def get_bounds(ds):
    """Extract the bounding box in projection coordinates.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset

    Returns
    -------
    tuple
        The bounding box in projection coordinates
        (left, bottom, right, top).
    """

    trans = get_transform(ds)
    if trans is not None:
        if isinstance(ds, xr.Dataset):
            dims = ds.dims
        elif isinstance(ds, xr.DataArray):
            dims = dict(zip(ds.dims, ds.shape))
        n_rows = dims['y']
        n_cols = dims['x']
        corners = (np.array([0, 0, n_cols-1, n_cols-1]),
                   np.array([0, n_rows-1, 0, n_rows-1]))
        corner_x, corner_y = trans * corners
        return BoundingBox(
            left=corner_x.min(),
            bottom=corner_y.min(),
            right=corner_x.max(),
            top=corner_y.max()
        )
    else:
        return BoundingBox(
            left=ds['x'].min(),
            bottom=ds['y'].min(),
            right=ds['x'].max(),
            top=ds['y'].max()
        )


def get_extent(ds):
    """Extract the extent (bounding box) from the dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset

    Returns
    -------
    tuple
        The extent (left, bottom, right, top) in latitude and longitude
        coordinates.
    """

    #
    # Check if latitude and longitude are stored as coordinates.
    #
    if 'lon' in ds.coords and 'lat' in ds.coords:
        return BoundingBox(
            left=ds.lon.values.min(),
            bottom=ds.lat.values.min(),
            right=ds.lon.values.max(),
            top=ds.lat.values.max()
        )

    #
    # Otherwise, get extent from projection information
    # by projecting the corner coordinates onto EPSG:4326
    # to obtain the latitude and longitude at the four corners.
    #
    src_crs = get_crs(ds)
    if src_crs is None:
        raise CRSError('Could not determine the CRS.')

    dst_crs = CRS(init='epsg:4326')
    proj_bounds = get_bounds(ds)
    bounds = rasterio.warp.transform_bounds(
        src_crs, dst_crs, **proj_bounds._asdict()
    )
    return BoundingBox(*bounds)


def get_common_bounds(datasets):
    """Calculate the common bounding box of the input datasets.

    Parameters
    ----------
    datasets : list of xarray.Dataset
        The input datasets.

    Returns
    -------
    tuple
        The common bounding box (left, bottom, right, top) in projected
        coordinates.
    """
    bounds = []
    common_crs = get_crs(datasets[0])

    for ds in datasets:
        ds_bounds = get_bounds(ds)
        crs = get_crs(ds)
        proj_bounds = rasterio.warp.transform_bounds(
            crs, common_crs, **ds_bounds._asdict()
        )
        bounds.append(proj_bounds)

    # Get largest extent:
    bounds = np.array(bounds)
    common_bounds = np.concatenate((bounds[:, :2].min(axis=0),
                                    bounds[:, 2:].max(axis=0)))

    return BoundingBox(*common_bounds)


def get_common_extent(datasets):
    """Calculate the smallest extent that contains all of the input datasets.

    Parameters
    ----------
    datasets : list of xarray.Dataset
        The input datasets.

    Returns
    -------
    tuple
        The common extent (left, bottom, right, top) in latitude and longitude
        coordinates.
    """
    common_bounds = get_common_bounds(datasets)
    common_crs = get_crs(datasets[0])
    dst_crs = CRS(init='epsg:4326')
    extent = rasterio.warp.transform_bounds(
        common_crs, dst_crs, **common_bounds._asdict()
    )
    return BoundingBox(*extent)


def get_common_resolution(datasets, mode='min'):
    """Determine the common resolution of a list of datasets.

    Parameters
    ----------
    datasets : list of xarray.Dataset
        The input datasets.
    mode : str {'min', 'max', 'mean'}
        How to determine the common resolution if the individual resolutions
        differ.

        * ``min``: Return the smallest (best) resolution.

        * ``max``: Return the largest (worst) resolution.

        * ``mean``: Return the average resolution.

    Returns
    -------
    tuple
        Returns the common resolution as (x, y).
    """

    if mode not in ['min', 'max', 'mean']:
        raise ValueError("Unsupported mode: '{}'".format(mode))

    # Raise an error if not all CRS are equal.
    crs = [get_crs(ds) for ds in datasets]
    if not all(map(lambda c: c == crs[0], crs)):
        raise ValueError('All datasets must have the same projection.')
    resolutions = np.array([get_resolution(ds) for ds in datasets])
    if mode == 'min':
        return tuple(resolutions.min(axis=0))
    elif mode == 'max':
        return tuple(resolutions.max(axis=0))
    elif mode == 'mean':
        return tuple(resolutions.mean(axis=0))


def get_dims(ds):
    if isinstance(ds, xr.Dataset):
        return dict(ds.dims)
    elif isinstance(ds, xr.DataArray):
        return dict(zip(ds.dims, ds.shape))


def nrows(ds):
    return get_dims(ds)['y']


def ncols(ds):
    return get_dims(ds)['x']


def _add_latlon(ds, n=50):
    """Add latitude and longitude coordinates to a dataset.

    This is required to allow e.g. SNAP to correctly determine the gecoding
    from the dataset when displaying the data.

    Parameters
    ----------
    ds : xarray.Dataset or xarray.DataArray
        The input dataset.
    n : int, optional
        The number of points in each dimension (default: 10).
    """

    nx = ncols(ds)
    ny = nrows(ds)
    src_crs = get_crs(ds)
    dst_crs = CRS(init='epsg:4326')
    idx_x = np.linspace(0, nx - 1, n, dtype=int)
    idx_y = np.linspace(0, ny - 1, n, dtype=int)
    xs = ds.x[idx_x]
    ys = ds.y[idx_y]
    xgrid, ygrid = np.meshgrid(xs, ys)
    lon, lat = rasterio.warp.transform(src_crs, dst_crs, xgrid.flatten(),
                                       ygrid.flatten())
    lon_sparse = np.empty((ny, nx))
    lat_sparse = np.empty((ny, nx))
    lon_sparse[:] = np.nan
    lat_sparse[:] = np.nan
    # idx_y needs to be a column vector
    lon_sparse[idx_y[:, None], idx_x] = np.array(lon).reshape((n, n))
    lat_sparse[idx_y[:, None], idx_x] = np.array(lat).reshape((n, n))
    ds.coords['lat'] = (('y', 'x'), lat_sparse)
    ds.coords['lon'] = (('y', 'x'), lon_sparse)


def _reproject(ds, dst_crs=None, dst_transform=None, width=None, height=None,
               res=None, extent=None, **kwargs):
    """Reproject a Dataset or DataArray.

    Parameters
    ----------
    ds : xarray.Dataset or xarray.DataArray
        The input dataset
    dst_crs : CRS-like, optional
        An object that can be parsed into a CRS. By default, use the same
        CRS as the input dataset.
    dst_transform : affine.Affine, optional
        The geometric transform of the output dataset.
    width : int, optional
        The width of the output dataset.
    height : int, optional
        The height of the output dataset.
    res : tuple (float, float), optional
        The resolution of the output dataset.
    extent : tuple, optional
        The output extent. By default this is determined from the input data.
    **kwargs : dict, optional
        Extra keyword arguments for ``rasterio.warp.reproject``.

    Returns
    -------
    xarray.Dataset or xarray.DataArray
        The projected dataset.
    """

    src_crs = get_crs(ds)
    src_bounds = get_bounds(ds)
    if extent is not None:
        extent = BoundingBox(*extent)

    #
    # Only allow inferring of width or height from aspect ratio
    # if the CRS is not changed.
    #
    if dst_crs is None:
        dst_crs = src_crs
        if width is None and height is not None:
            width = int(ncols(ds) * height / nrows(ds))
        elif height is None and width is not None:
            height = int(nrows(ds) * width / ncols(ds))

    # Given: transform, shape
    # Given: transform, extent
    # Given: res, extent
    # Given: shape, res
    # Given: shape, extent

    if dst_transform is not None:
        #
        # If the transform is given, we also need the width and height or
        # the extent.
        #
        if width is not None and height is not None:
            pass
        elif extent is not None:
            # Calculate width and height from extent
            width = int(abs(
                (extent.right - extent.left) / dst_transform.a)) + 1
            height = int(abs(
                (extent.top - extent.bottom) / dst_transform.e)) + 1
        else:
            raise ValueError('Not enough information provided.')

    elif extent is not None:
        #
        # Transform can be calculated from extent, if either width and height
        # or the resolution are given.
        #
        if res is not None:
            width = int(abs(
                (extent.right - extent.left) / res[0])) + 1
            height = int(abs(
                (extent.top - extent.bottom) / res[1])) + 1

        # The following doesn't give the correct result.
        dst_transform = rasterio.transform.from_bounds(
            *extent, width=width-1, height=height-1
        )

    else:
        #
        # If neither the transform nor the extent are given, infer the best
        # possible parameters from the width, height, and the resolution.
        #
        dst_transform, width, height = \
            rasterio.warp.calculate_default_transform(
                src_crs, dst_crs,
                ncols(ds), nrows(ds),
                resolution=res,
                dst_width=width,
                dst_height=height,
                **src_bounds._asdict())

    src_transform = get_transform(ds)
    src_dims = _get_dim_order(ds)
    dst_crs = _parse_crs(dst_crs)

    #
    # Prepare new x and y coordinate arrays
    #
    dst_x, _ = dst_transform * (np.arange(width), np.zeros(width, dtype=int))
    _, dst_y = dst_transform * (np.zeros(height, dtype=int), np.arange(height))
    dst_coords = {'x': dst_x, 'y': dst_y}

    #
    # Handle the case where there are extra dimensions, e.g. 'time'
    # or 'band'
    #
    extra_dims = set(src_dims) - {'y', 'x'}

    for c in extra_dims:
        dst_coords[c] = ds.coords[c]

    def _reproject_da(da, shape):
        #
        # Reproject a single data array
        #
        coord_dims = tuple(c for c in ('y', 'x') if c in da.dims)
        extra_dims = set(da.dims) - set(coord_dims)
        # Preserve original dimension order
        orig_dim_order = _get_dim_order(da)
        ordered_extra_dims = \
            tuple(d for d in orig_dim_order if d in extra_dims)
        dim_order = ordered_extra_dims + coord_dims

        # Determine best resampling method from data type
        if np.issubdtype(da.dtype, np.integer):
            nodata = 0
            default_resampling = rasterio.warp.Resampling.nearest
        else:
            nodata = np.nan
            default_resampling = rasterio.warp.Resampling.bilinear
        if 'resampling' not in kwargs:
            kwargs['resampling'] = default_resampling

        # Get values as numpy array such that last two axes are
        # y and x
        values = da.transpose(*dim_order, transpose_coords=True).values

        # Flatten multidimensional data to ONE extra dimension
        if values.ndim > 2:
            output_shape = values.shape[:-2] + shape
            values = values.reshape((-1,) + values.shape[-2:])
            output_shape_flat = (values.shape[0],) + shape
        else:
            output_shape = shape
            output_shape_flat = shape

        output = np.zeros(output_shape_flat, dtype=da.dtype)
        output[:] = np.nan

        # Fix data shape for one-dimensional data
        if da.ndim == 1:
            #
            # NOTE: The stretch factor is necessary because the input data
            # must extend at least half an original resolution cell in the
            # independent dimension.
            #
            if da.dims == ('x',):
                stretch_x = int((~src_transform * dst_transform).a / 2 + 1)
                values = np.vstack([values] * stretch_x)
                output.shape = (1,) + output.shape
            elif da.dims == ('y',):
                stretch_y = int((~src_transform * dst_transform).e / 2 + 1)
                values = np.vstack([values] * stretch_y).T
                output.shape = output.shape + (1,)

        rasterio.warp.reproject(
            values,
            output,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=nodata,
            **kwargs
        )

        # Final reshape in case the input was one-dimensional
        return output.reshape(output_shape)

    if isinstance(ds, xr.Dataset):
        result = xr.Dataset(coords=dst_coords)

        #
        # Also reproject coordinate arrays that are defined over
        # x and y
        #
        for v in ds.coords:
            #
            # If the projection is the same, also reproject coordinate arrays
            # that are defined over only one variable.
            #
            if dst_crs == src_crs and v not in ds.dims:
                if ds.coords[v].dims == ('x',):
                    result.coords[v] = \
                        (('x',), _reproject_da(ds.coords[v], (width,)))
                elif ds.coords[v].dims == ('y',):
                    result.coords[v] = \
                        (('y',), _reproject_da(ds.coords[v], (height,)))

            if not set(ds.coords[v].dims).issuperset({'x', 'y'}):
                continue

            shape = (height, width)
            result.coords[v] = (('y', 'x'),
                                _reproject_da(ds.coords[v], shape))

        #
        # Reproject the actual data
        #
        for v in ds.data_vars:
            vdims = _get_projection_dim_order(ds[v])
            if set(ds[v].dims) == set(vdims) or set(ds[v].dims) == {'y', 'x'}:
                shape = (height, width)
                result[v] = (vdims, _reproject_da(ds[v], shape))
            else:
                # The variable doesn't contain y and x dimensions.
                result[v] = (ds[v].dims, ds[v])

        #
        # Create lat and lon coordinates
        #
        # if 'lat' in ds.coords and 'lon' in ds.coords:
        #     lon, lat = rasterio.warp.transform(
        #         src_crs, dst_crs, ds.coords['x'], ds.coords['y'])
        #     result.coords['lon'] = (('x',), lon)
        #     result.coords['lat'] = (('y',), lat)

    elif isinstance(ds, xr.DataArray):
        shape = (height, width)
        dst_dims = _get_projection_dim_order(ds)
        result = xr.DataArray(_reproject_da(ds, shape), dims=dst_dims,
                              coords=dst_coords, name=ds.name)

    # Reorder dimensions to match original.
    result = result.transpose(*_get_dim_order(ds))

    #
    # Add metadata
    #
    result.attrs = ds.attrs

    # Serialize transform to tuple and store in metadata
    result.attrs['transform'] = dst_transform[:6]
    # Store CRS info in metadata
    result.attrs['crs'] = dst_crs.to_string()
    result.attrs['coordinate_system_string'] = dst_crs.wkt
    # Store new data shape in metadata
    result.attrs['lines'] = nrows(result)
    result.attrs['samples'] = ncols(result)

    _add_latlon(result)

    return result


class Reprojection(Algorithm):
    """Reprojection of the dataset to the given coordinate reference system
    (CRS) and extent.

    Parameters
    ----------
    target : xarray.Dataset or xarray.DataArray, optional
        A reference to which a dataset will be aligned.
    crs : dict or str
        The output coordinate reference system as dictionary or proj-string
    extent : tuple, optional
        The output extent. By default this is determined from the input data.
    **kwargs : dict, optional
        Extra keyword arguments for ``rasterio.warp.reproject``.
    """

    def __init__(self, target=None, crs=None, extent=None, res=None,
                 width=None, height=None, transform=None, **kwargs):
        if target is not None:
            # Parse target information
            for param in ['crs', 'transform', 'width', 'height', 'extent',
                          'res']:
                if locals()[param] is not None:
                    warnings.warn('`{}` is ignored if `target` is '
                                  'specified.'.format(param))

            crs = get_crs(target)
            transform = get_transform(target)
            width = ncols(target)
            height = nrows(target)
            res = extent = None

        elif transform is not None and (width is None or height is None):
            raise ValueError('If `transform` is given, you must also specify '
                             'the `width` and `height` arguments.')

        elif extent is not None and res is None and \
                (width is None or height is None):
            raise ValueError('Need to provide either `width` and `height` or '
                             'resolution when specifying the extent.')

        self.crs = _parse_crs(crs)
        self.extent = extent
        self.res = res
        self.width = width
        self.height = height
        self.transform = transform
        self.kwargs = kwargs

    def apply(self, ds):
        """Apply the projection to a dataset.

        Parameters
        ----------
        ds : xarray.Dataset
            The input dataset.

        Returns
        -------
        xarray.Dataset
            The reprojected dataset.
        """

        return _reproject(ds, dst_crs=self.crs, dst_transform=self.transform,
                          width=self.width, height=self.height, res=self.res,
                          extent=self.extent, **self.kwargs)


reproject = wrap_algorithm(Reprojection, 'reproject')


class Resample(Algorithm):
    """Resample a dataset to the specified resolution or width and height.

    Parameters
    ----------
    res : float or tuple, optional
        The desired resolution in the dataset coordinates.
    width : int, optional
        The desired output width. Ignored if the resolution is specified.
        If only the height is given, the width is calculated automatically.
    height : int, optional
        The desired output height. Ignored if the resolution is specified.
        If only the width is given, the height is calculated automatically.
    **kwargs : dict, optional
        Extra keyword arguments for ``rasterio.warp.reproject``.
    """

    def __init__(self, res=None, width=None, height=None, **kwargs):
        self.res = res
        self.width = width
        self.height = height
        self.kwargs = kwargs

    def apply(self, ds):
        """Resample the dataset.

        Parameters
        ----------
        ds : xarray.Dataset or xarray.DataArray
            The input dataset

        Returns
        -------
        xarray.Dataset or xarray.DataArray
            The resampled dataset.
        """

        return _reproject(ds, width=self.width, height=self.height,
                          res=self.res, **self.kwargs)


resample = wrap_algorithm(Resample, 'resample')


class Alignment(Algorithm):
    """Align a list of datasets to the same coordinate grid.

    Parameters
    ----------
    target : xarray.Dataset, optional
        Align the datasets with respect to the target dataset.
    crs : str or dict, optional
        The coordinate reference system as proj-string or dictionary.
        By default, use the CRS of the datasets.
    extent : tuple, optional
        The bounding box of the output dataset. By default, use the common
        extent of all datasets.
    """

    def __init__(self, target=None, crs=None, extent=None):
        self.target = target
        self.crs = crs
        self.extent = extent

    def apply(self, datasets, path):
        """Resample datasets to common extent and resolution.

        Parameters
        ----------
        datasets : str, list of str, list of xarray.Dataset
            The input datasets. Can be either a glob expression,
            a list of filenames, or a list of opened datasets.
        path : str
            The output path to store the aligned datasets.
        """

        # Treat `datasets` as a glob expression
        if isinstance(datasets, str):
            datasets = glob.glob(datasets)

        if len(datasets) == 0:
            raise ValueError("No files found!")

        # Treat `datasets` as a list of file paths
        products = datasets
        if isinstance(datasets[0], str):
            # Pass chunks={} to ensure the dataset is read as a dask array
            product_names = [os.path.splitext(os.path.split(_)[1])[0]
                             for _ in products]
            datasets = [open_dataset(d, as_complex=False) for d in datasets]
        else:
            product_names = [ds.metadata.attrs['Abstracted_Metadata:PRODUCT']
                             if 'metadata' in ds else 'data{}'.format(i)
                             for i, ds in enumerate(datasets)]

        os.makedirs(path, exist_ok=True)

        if self.extent is None:
            extent = get_common_bounds(datasets)
        else:
            extent = self.extent

        # This is the resolution in the source CRS.
        # TODO: Need to reproject into target dataset.
        res = get_common_resolution(datasets)

        crs = self.crs
        if crs is None:
            crs = get_crs(datasets[0])

        proj = Reprojection(crs=crs, extent=extent, res=res)
        for name, ds in zip(product_names, products):
            outfile = os.path.join(path, name + '_aligned.nc')
            if isinstance(ds, str):
                ds = open_dataset(ds, as_complex=False)
            res = proj.apply(ds)
            to_netcdf(res, outfile)
            del res


align = wrap_algorithm(Alignment, 'align')


# --------------
# COREGISTRATION
# --------------

class Coregistration(Algorithm):
    """Coregister a time series (stack) of images to a master image.

    At the moment only supports coregistration by translation.

    Parameters
    ----------
    reference : int, optional
        The time index to use as reference for coregistration (default: 0).
    upsampling : int, optional
        The upsampling factor for shift estimation (default: 10).
    """

    def __init__(self, reference=0, upsampling=10):
        self.reference = reference
        self.upsampling = upsampling

    def apply(self, ds):
        """Apply the projection to a dataset.

        Parameters
        ----------
        ds : xarray.Dataset
            The input dataset.

        Returns
        -------
        xarray.Dataset
            The coregistered dataset.
        """
        return _coregister(ds, reference=self.reference,
                           upsampling=self.upsampling)


def _coregister(ds, reference, upsampling, order=3):
    ref_var = 'C11'
    ds_new = disassemble_complex(ds)
    ref = ds_new.isel(time=reference)[ref_var].values
    datavars = get_vars_for_dims(ds_new, ['time', 'x', 'y'])
    # Coregister each time step independently
    for t in range(ds_new.dims['time']):
        if t == reference:
            continue
        src = ds_new.isel(time=t)
        # Estimate shift
        shift = skimage.feature.register_translation(
            src[ref_var].values, ref, upsample_factor=upsampling)
        translation = (shift[0][1], shift[0][0])
        # Create transform object
        transf = skimage.transform.AffineTransform(translation=translation)
        # Apply transform to each variable
        for v in datavars:
            # For assignment, need to use .loc rather than .isel
            ds_new[v].loc[dict(time=ds['time'][t])] = skimage.transform.warp(
                src[v].values, transf, order=order)
    return ds_new


coregister = wrap_algorithm(Coregistration, 'coregister')