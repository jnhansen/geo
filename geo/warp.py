"""
This module contains all functionality related to reprojecting a
dataset.

TODO: Make all functions work with xarray Datasets.
TODO: remove clutter in main()

"""
# somehow need to import gdal first ...
from osgeo import gdal, osr
import numpy as np
import pandas as pd
import xarray as xr
# import multiprocessing as mp
from scipy.ndimage.interpolation import map_coordinates
# from transform import map_coordinates_wrapper
from utils import array_chunks

try:
    type(profile)
except NameError:
    def profile(fn): return fn

NO_DATA_VALUE = np.nan

# def _get_gcp_extent(src):
#     gcp_df = get_gcp_df(src)
#     lon = gcp_df['GCPX']
#     lat = gcp_df['GCPY']
#     return [lon.min(), lat.min(), lon.max(), lat.max()]


# @profile
# def _get_warp_coords(src, shape=None, extent=None):
#     #
#     # Prepare the output data array (decide on resolution here).
#     #
#     if extent is None:
#         extent = _get_gcp_extent(src)
#     if shape is None:
#         N_lat, N_lon = src.RasterYSize, src.RasterXSize
#     else:
#         N_lat, N_lon = shape
#     # output_lon_start = output_lon_range[0]
#     # output_lat_start = output_lat_range[0]
#     # lonlat_step = 0
#     # latlon_step = 0
#     # lat_step = (output_lat_range[1] - output_lat_range[0]) / (N_lat - 1)
#     # lon_step = (output_lon_range[1] - output_lon_range[0]) / (N_lon - 1)

#     ll2xy = latlon_fit(src, degree=3, inverse=True)
#     grid_ll = np.meshgrid(
#         np.linspace(extent[0], extent[2], N_lon),
#         np.linspace(extent[1], extent[3], N_lat),
#         copy=False
#     )
#     lon_flat = grid_ll[0].flatten()
#     lat_flat = grid_ll[1].flatten()
#     ll = np.stack([lon_flat, lat_flat], axis=-1)
#     coords = ll2xy(ll)
#     coords = coords.T
#     coords = coords.reshape((2, N_lat, N_lon))
#     return coords, extent


@profile
def _map_single_raster(arr, coords):
    if np.iscomplexobj(arr):
        # interpolate magnitude and phase separately
        mapped_mag = map_coordinates(np.abs(arr), coords, output=np.float32,
                                     order=3, cval=NO_DATA_VALUE)
        mapped_phase = map_coordinates(np.angle(arr), coords,
                                       output=np.float32, order=3,
                                       cval=NO_DATA_VALUE)
        mapped = mapped_mag * np.exp(1j * mapped_phase)
    else:
        mapped = map_coordinates(arr, coords, output=np.float32, order=3,
                                 cval=NO_DATA_VALUE)
    return mapped


def _efficient_map_coordinates(arr, coords, order, cval):
    return map_coordinates(arr, coords, output=np.float32, order=order,
                           cval=cval)


# @profile
# def warp(src, output_shape=None, extent=None, nproc=1, fake=False):
#     """Warps a GDAL dataset onto a lat-lon grid (equirectangular projection).

#     It is assumed that the dataset contains a list of GCPs for
#     georeferencing.

#     TODO: Deprecate?

#     Parameters
#     ----------
#     src : osgeo.gdal.Dataset
#     output_shape : tuple, opt
#         The shape of the output raster (default: None).
#         If None, infer from data.
#     extent : list, opt
#         The lat-lon extent of the output raster as
#         [llcrnrlon, llcrnrlat, urcrnrlon, urcrnrlat] (default: None).
#         If None, infer from data.
#     nproc : int, opt
#         The number of parallel processes to use (default: 1).

#     Returns
#     -------
#     osgeo.gdal.Dataset
#         A warped dataset. The georeferencing is encoded in the transform
#         matrix that can be accessed as
#         `osgeo.gdal.Dataset.GetGeoTransform()`.
#     """
#     N_bands = src.RasterCount
#     coords, extent = _get_warp_coords(src, shape=output_shape, extent=extent)
#     N_lat, N_lon = coords.shape[1:]

#     #
#     # Create GDAL dataset from numpy array.
#     #
#     tmp = gdal.GetDriverByName('MEM').Create('', N_lon, N_lat, N_bands,
#                                              gdal.GDT_Float32)

#     if nproc == 1:
#         warped = [_map_single_raster(src.GetRasterBand(i+1).ReadAsArray(),
#                                      coords) for i in range(N_bands)]
#     else:
#         kwargs_list = [dict(input=src.GetRasterBand(i+1).ReadAsArray(),
#                             coordinates=coords, output=np.float32, order=3,
#                             cval=NO_DATA_VALUE) for i in range(N_bands)]
#         pool = mp.Pool(min(nproc, N_bands))
#         result = pool.map_async(map_coordinates_wrapper, kwargs_list)
#         pool.close()
#         pool.join()
#         warped = result.get()

#     for i in range(N_bands):
#         org_band = src.GetRasterBand(i+1)
#         new_band = tmp.GetRasterBand(i+1)
#         new_band.WriteArray(warped[i])
#         new_band.SetNoDataValue(NO_DATA_VALUE)
#         new_band.SetMetadata(org_band.GetMetadata())

#     extent = _get_gcp_extent(src)
#     output_lon_start = extent[0]
#     output_lat_start = extent[1]
#     lonlat_step = 0
#     latlon_step = 0
#     lat_step = (extent[3] - extent[1]) / (N_lat - 1)
#     lon_step = (extent[2] - extent[0]) / (N_lon - 1)
#     transform = (output_lon_start, lon_step, lonlat_step,
#                  output_lat_start, latlon_step, lat_step)
#     tmp.SetGeoTransform(transform)
#     tmp.SetMetadata(src.GetMetadata())
#     return tmp


# NOTE: deprecate?
def gdal_warp(src):
    """ Warps a GDAL dataset onto EPSG:4326, i.e. a lat-lon grid.
    https://gis.stackexchange.com/a/140053

    Parameters
    ----------
    src : osgeo.gdal.Dataset

    Returns
    -------
    osgeo.gdal.Dataset
        A dataset warped onto EPSG:4326 (lat-lon grid)
    """
    # Define target SRS
    dst_srs = osr.SpatialReference()
    dst_srs.ImportFromEPSG(4326)
    dst_wkt = dst_srs.ExportToWkt()

    error_threshold = 0.125
    resampling = gdal.GRA_Bilinear
    # resampling = gdal.GRA_NearestNeighbour

    # The second argument is src_wkt :
    # left to default value --> will use the one from source
    warped_ds = gdal.AutoCreateWarpedVRT(src,
                                         None,
                                         dst_wkt,
                                         resampling,
                                         error_threshold)

    return warped_ds


def map_coordinates_with_nan(input, coords, *args, **kwargs):
    """
    An extension of map_coordinates that can handle np.nan values in the
    input array.
    """
    nanmask = np.isnan(input).astype(np.float32)
    if nanmask.sum() > 0:
        nanmask_mapped = map_coordinates(nanmask, coords, output=np.float32,
                                         cval=1) > 0.9
    else:
        nanmask_mapped = np.zeros_like(coords)
    filled_input = input.copy()
    filled_input[np.isnan(filled_input)] = 0
    result = map_coordinates(filled_input, coords, *args, **kwargs)
    result[nanmask_mapped.astype(bool)] = np.nan
    return result


def _fit_latlon(coords, degree=3, inverse=False, return_coef=False):
    """Fit a polynomial to the input coordinates.

    NOTE: This function will not need to be called in the public API.

    Parameters
    ----------
    coords : numpy.array (M, N, 2) or pandas.DataFrame
        Either a numpy array of lat/lon coordinates, or a pandas DataFrame
        with the columns ['GCPLine', 'GCPPixel', 'GCPX', 'GCPY'] containing
        the Ground Control Points.
    degree : int, optional
        The polynomial degree to be fitted (default: 3)
    inverse : bool, optional
        If True, fit x,y as function of lon,lat (default: False).
    return_coef : bool, optional
        If True, return the coefficients of the fitted polynomial.
        Otherwise, return a function that converts between (x,y) and (lat,lon).
        (default: False)

    Returns
    -------
    function
        If `inverse` is False, the returned function converts (y,x) to
        (lon,lat). Otherwise, the function returns (lon,lat) for an input of
        (y,x).
    """
    from sklearn.preprocessing import PolynomialFeatures
    from sklearn import linear_model
    poly = PolynomialFeatures(degree=degree)

    if isinstance(coords, pd.DataFrame):
        #
        # GCPs
        #
        must_contain = ['GCPLine', 'GCPPixel', 'GCPX', 'GCPY']
        if not coords.columns.isin(must_contain).all():
            raise ValueError("The DataFrame `coords` must contain the columns"
                             " ['GCPLine', 'GCPPixel', 'GCPX', 'GCPY'].")
        ll = coords[['GCPX', 'GCPY']]
        xy = coords[['GCPLine', 'GCPPixel']]
    else:
        #
        # Lat-Lon grid
        #
        if not isinstance(coords, np.ndarray):
            raise ValueError("`coords` is not a valid numpy array.")
        if coords.ndim != 3 or coords.shape[2] != 2:
            raise ValueError("`coords` must have shape (rows, cols, 2)."
                             " Found shape %s instead." % repr(coords.shape))

        y, x = np.meshgrid(np.arange(coords.shape[1]),
                           np.arange(coords.shape[0]),
                           copy=False)

        # subsample
        step = 50
        ll = coords[::step, ::step, :]
        xy = np.stack((y[::step, ::step], x[::step, ::step]), axis=-1)
        # remove nan coordinates and flatten
        mask = np.isnan(ll).any(axis=2)
        ll = ll[~mask]
        xy = xy[~mask]

    if inverse:
        regressor = poly.fit_transform(ll)
        regressand = xy
    else:
        regressor = poly.fit_transform(xy)
        regressand = ll

    clf = linear_model.LinearRegression()
    clf.fit(regressor, regressand)

    if return_coef:
        return clf.coef_

    else:
        def fn(X):
            """
            This function maps from (x,y) to (lon,lat) (or the reverse).
            """
            if not isinstance(X, np.ndarray):
                X = np.array(X)
            orig_shape = X.shape

            if len(orig_shape) == 1:
                # single coordinate pair was passed
                X = np.array([X])
            elif len(orig_shape) == 3:
                # flatten X temporarily
                X = X.reshape(-1, 2)

            #
            # If X is very large, split into chunks.
            #
            # Empirical optimal chunk sizes (approximately):
            # chunk size | len(X) | degree
            # -----------|--------|--------
            # 8000       | 1e8    | 3
            # 8000       | 1e8    | 2
            res = np.empty_like(X)
            for index, chunk in array_chunks(X, 8000, axis=0,
                                             return_indices=True):
                p = poly.transform(chunk)
                res[index] = clf.predict(p)

            # reshape back to original shape:
            if len(orig_shape) != 2:
                res = res.reshape(orig_shape)

            return res

        return fn


def _coord_transform(coords, new_coords):
    """Generate an array of image space coordinates that will transform
    from `coords` to `new_coords`.

    Parameters
    ----------
    coords : numpy.array, shape (M, N, 2)
        The original coordinates of each pixel.
    new_coords : numpy.array, shape (Y, X, 2)
        The new coordinates.

    Returns
    -------
    numpy.array, shape (Y, X, 2)
        The image coordinates corresponding to the transform.
    """
    # 1) find the function coord2xy for coords.
    coord2xy = _fit_latlon(coords, inverse=True)
    # 2) apply coord2xy to new_coords.
    im_coords = coord2xy(new_coords)

    return im_coords


def resample_grid(dataset, shape, extent):
    """Resample a dataset to a new shape and extent.

    Parameters
    ----------
    dataset : xarray.Dataset
        The dataset to resample.
    shape : tuple
        The shape of the output dataset.
    extent : array_like
        The extent of the output dataset.

    Returns
    -------
    xarray.Dataset
        A new dataset with shape `shape` and extent `extent`.
    """
    new_coords = dict(dataset.coords)
    new_coords['lat'] = np.linspace(extent[0], extent[2], shape[0])
    new_coords['lon'] = np.linspace(extent[1], extent[3], shape[1])

    lon_grid, lat_grid = np.meshgrid(new_coords['lon'], new_coords['lat'],
                                     copy=False)
    latlon_grid = np.stack([lat_grid, lon_grid], axis=0)

    org_ll_min = np.array([[[dataset.lat.min()]], [[dataset.lon.min()]]])
    org_ll_range = np.array([[[dataset.lat.max()]],
                             [[dataset.lon.max()]]]) - org_ll_min
    org_ll_shape = np.array([[[dataset.sizes['lat']]],
                             [[dataset.sizes['lon']]]]) - 1
    coord_grid = (latlon_grid - org_ll_min) * (org_ll_shape/org_ll_range)

    result = xr.Dataset(coords=new_coords, attrs=dataset.attrs)
    for var in dataset.data_vars:
        result[var] = (('lat', 'lon'),
                       map_coordinates_with_nan(dataset[var].values,
                                                coord_grid, output=np.float32,
                                                order=2, cval=np.nan))

    return result


def resample(data, new_coords, coords=None, order=3):
    """Resample data at new coordinates.

    The old and new coordinates will typically be in degrees latitude and
    longitude, but may be in arbitrary units as long as they share the same
    coordinate system.

    NOTE: This is a lower-level function used by warp_dataset().

    Parameters
    ----------
    data : numpy.array, shape (M, N, L)
        The original data, L is the number of bands.
    new_coords : numpy.array, shape (Y, X, 2)
        The new coordinates for which to resample data.
    coords : numpy.array, shape (M, N, 2), optional
        The coordinates of each pixel in `data`. If None, it is assumed that
        `new_coords` is already in image coordinates (default: None).
    order : int, optional
        The polynomial order (default: 3).

    Returns
    -------
    numpy.array, shape (Y, X, L)
        `data` resampled to the new coordinates.
    """
    if data.ndim == 3:
        channels = data
    elif data.ndim == 2:
        channels = data[..., np.newaxis]
    else:
        raise ValueError("`data` has an unsupported shape: %s" % data.shape)

    M, N, L = channels.shape
    Y, X, _ = new_coords.shape

    # from coords and new_coords figure out the corresponding
    # image coordinates.
    if coords is None:
        im_coords = new_coords
    else:
        im_coords = _coord_transform(coords, new_coords)

    im_coords = im_coords.transpose((2, 0, 1))

    mapped = np.empty((Y, X, L), dtype=data.dtype)

    for channel in range(L):
        # warp data onto the new image coordinates
        cdata = channels[:, :, channel]
        if np.iscomplexobj(cdata):
            # interpolate magnitude and phase separately
            out_dtype = np.float32 if cdata.dtype is np.complex64 \
                        else np.float64
            mapped_mag = map_coordinates(np.abs(cdata), im_coords,
                                         output=out_dtype, order=order,
                                         cval=np.nan)
            mapped_phase = map_coordinates(np.angle(cdata), im_coords,
                                           output=out_dtype, order=order,
                                           cval=np.nan)
            mapped[:, :, channel] = mapped_mag * np.exp(1j * mapped_phase)
        else:
            mapped[:, :, channel] = \
                map_coordinates(cdata, im_coords, output=np.float32,
                                order=order, cval=np.nan)
    if data.ndim == 2:
        mapped = mapped[:, :, 0]

    return mapped


def warp_dataset(ds, extent=None, shape=None):
    """Warp a dataset onto equirectangular coordinates. The resulting dataset
    will contain 'lat' and 'lon' as 1-dimensional coordinate variables, i.e.
    dimensions.

    TODO: parallelize

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset that must contain coordinate variables 'lat' and 'lon',
        which may be NaN in most places (tie point grid).
    extent : list, optional
        The desired extent of the warped dataset in the form
        [llcrnrlon, llcrnrlat, urcrnrlon, urcrnrlat]. If None (default),
        take the maximum extent spanned my the original dataset.
    shape : tuple, optional
        The desired shape of the output dataset. This will determine the
        resolution. If None (default), the output shape will be equal to the
        input shape, which may not be desirable.

    Returns
    -------
    xarray.Dataset
        A warped dataset of shape `shape`.
    """
    if not isinstance(ds, xr.Dataset):
        raise ValueError("`ds` must be a valid xarray Dataset (got: {})."
                         .format(type(ds)))
    gcps = _tie_points_to_gcps(ds)
    ll2xy = _fit_latlon(gcps, inverse=True)
    if extent is None:
        # [llcrnrlon, llcrnrlat, urcrnrlon, urcrnrlat]
        extent = [gcps['GCPX'].min(), gcps['GCPY'].min(),
                  gcps['GCPX'].max(), gcps['GCPY'].max()]
    if shape is None:
        shape = ds.lat.shape
    N_lat, N_lon = shape
    new_lons = np.linspace(extent[0], extent[2], N_lon)
    new_lats = np.linspace(extent[1], extent[3], N_lat)
    new_ll_coords = np.stack(np.meshgrid(new_lons, new_lats, copy=False),
                             axis=-1)
    new_image_coords = ll2xy(new_ll_coords)

    #
    # Create new dataset
    #
    ds_warped = xr.Dataset(coords={'lat': new_lats, 'lon': new_lons,
                                   'time': ds.time},
                           attrs=ds.attrs)
    # Warp the data variables
    for name, var in ds.data_vars.items():
        new_data = resample(var.values, new_image_coords)
        ds_warped[name] = (('lat', 'lon'), new_data)

    return ds_warped


def _tie_points_to_gcps(ds):
    """Given an input dataset with tie point grids, generate a DataFrame
    of the GCPs.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset containing lat/lon tie point grids.

    Returns
    -------
    pandas DataFrame
        The GCPs as DataFrame.
    """
    if 'lat' not in ds or 'lon' not in ds:
        raise ValueError("The dataset must contain 'lat' and 'lon'.")
    mask = ~np.isnan(ds.lat)
    ncols, nrows = ds.lat.shape
    y, x = np.meshgrid(np.arange(nrows), np.arange(ncols), copy=False)
    gcp_dict = {'GCPX': ds.lon.values[mask],
                'GCPY': ds.lat.values[mask],
                'GCPPixel': y[mask],
                'GCPLine': x[mask]}
    gcps = pd.DataFrame(gcp_dict)
    return gcps


# def add_gcps_to_dataset(ds, gcps):
#     pass


if __name__ == '__main__':
    pass