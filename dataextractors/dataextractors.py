# Extract pixels and metadata using geojsons and georeferenced imagery.
# The purpose of this module is to generate train, test and target data
# for machine learning algorithms.

import geoio
import geojson
import geojsontools as gt
import numpy as np
import sys, os
import subprocess
import warnings
import osgeo.gdal as gdal
from scipy.misc import imresize
from itertools import cycle
from osgeo.gdalconst import *
from functools import reduce


def get_data(input_file, return_labels=False, return_id=False, buffer=[0, 0], mask=False,
             num_chips=None):
    '''
    Return pixel intensity array for each geometry in input_file. The image reference for
        each geometry is found in the image_id property of the input file. If input_file
        contains points, then buffer must have non-zero entries. The function also can
        also return a list of geometry ids; this is useful in case some of the input file
        entries do not produce a valid intensity array and/or class name.

    Args:
        input_file (str): Name of geojson file.
        return_labels (bool): If True, then a label vector is returned.
        return_id (bool): if True, then the geometry id is returned.
        buffer (list): 2-dim buffer in PIXELS. The size of the box in each dimension is
            TWICE the buffer size.
        mask (bool): Return a masked array.
        num_chips (int): Maximum number of arrays to return.

    Returns:
        chips (list): List of pixel intensity numpy arrays.
        ids (list): List of corresponding geometry ids.
        labels (list): List of class names, if return_labels=True
    '''

    data, ct = [], 0

    # go through point_file and unique image_id's
    image_ids = gt.find_unique_values(input_file, property_name='image_id')

    # go through the geojson for each image --- this is how geoio works
    for image_id in image_ids:

        # add tif extension
        img = geoio.GeoImage(image_id + '.tif')

        for chip, properties in img.iter_vector(vector=input_file,
                                                properties=True,
                                                filter=[
                                                    {'image_id': image_id}],
                                                buffer=buffer,
                                                mask=mask):

            if chip is None or reduce(lambda x, y: x * y, chip.shape) == 0:
                continue

            # every geometry must have id
            if return_id:
                this_data = [chip, properties['feature_id']]
            else:
                this_data = [chip]

            if return_labels:
                try:
                    label = properties['class_name']
                    if label is None:
                        continue
                except (TypeError, KeyError):
                    continue
                this_data.append(label)

            data.append(this_data)

            # return if max num chips is reached
            if num_chips:
                ct += 1
                if ct == num_chips:
                    return zip(*data)

    return zip(*data)


def random_window(image, chip_size, no_chips=10000):
    '''
    Implement a random chipper on a georeferenced image.

    Args:
        image (str): Image filename.
        chip_size (list): Array of chip dimensions.
        no_chips (int): Number of chips.

    Returns:
        List of chip rasters.
    '''
    img = geoio.GeoImage(image)

    chips = []
    for i, chip in enumerate(img.iter_window_random(
            win_size=chip_size, no_chips=no_chips)):
        chips.append(chip)
        if i == no_chips - 1:
            break

    return chips


def apply_mask(input_file, mask_file, output_file):
    '''
    Apply binary mask on image. Input image and mask must have the same (x,y) dimension
        and the same projection.

    Args:
        input_file (str): Input file name.
        mask_file (str): Mask file name.
        output_file (str): Masked image file name.
    '''

    source_ds = gdal.Open(input_file, GA_ReadOnly)
    nbands = source_ds.RasterCount
    mask_ds = gdal.Open(mask_file, GA_ReadOnly)

    xsize, ysize = source_ds.RasterXSize, source_ds.RasterYSize
    xmasksize, ymasksize = mask_ds.RasterXSize, mask_ds.RasterYSize

    print 'Generating mask'

    # Create target DS
    driver = gdal.GetDriverByName('GTiff')
    dst_ds = driver.Create(output_file, xsize, ysize, nbands, GDT_Byte)
    dst_ds.SetGeoTransform(source_ds.GetGeoTransform())
    dst_ds.SetProjection(source_ds.GetProjection())

    # Apply mask --- this is line by line at the moment, not so efficient
    for i in range(ysize):
        # read line from input image
        line = source_ds.ReadAsArray(xoff=0, yoff=i, xsize=xsize, ysize=1)
        # read line from mask
        mask_line = mask_ds.ReadAsArray(xoff=0, yoff=i, xsize=xsize, ysize=1)
        # apply mask
        masked_line = line * (mask_line > 0)
        # write
        for n in range(1, nbands + 1):
            dst_ds.GetRasterBand(n).WriteArray(masked_line[n - 1].astype(np.uint8),
                                               xoff=0, yoff=i)
    # close datasets
    source_ds, dst_ds = None, None


def get_data_from_polygon_list(features, min_side_dim=0, max_side_dim=125, num_chips=None,
                               classes=None, normalize=True, return_id=False, bit_depth=8,
                               mask=True, show_percentage=True, assert_all_valid=False,
                               resize_dim=None, **kwargs):
    '''
    Extract pixel intensity arrays ('chips') from image strips given a list of polygon
        features from a geojson file. All chips will be of uniform size. Will only return
        chips whose side dimension is between min_side_dim and max_side_dim. Each image
        strip referenced in the image_id property must be in the working directory and
        named as follows: <image_id>.tif.

    Args
        features (list): list of polygon features from an open geojson file. IMPORTANT:
            Geometries must be in the same projection as the imagery! No projection
            checking is done!
        min_side_dim (int): minimum size acceptable (in pixels) for a polygon. defaults
            to 10.
        max_side_dim (int): maximum size acceptable (in pixels) for a polygon. Note that
            this will be the size of the height and width of all output chips. defaults
            to 125.
        num_chips (int): Maximum number of chips to return. If None, all valid chips from
            features will be returned. Defaults to None.
        classes (list['string']): name of classes for chips. If None no labels will be
            returned. Defaults to None.
        normalize (bool): divide all chips by max pixel intensity (normalize net
            input). Defualts to True.
        return_id (bool): return the feature id with each chip. Defaults to False.
        return_labels (bool): Include labels in output. Labels will be numerical
            and correspond to the class index within the classes argument. Defualts
            to True.
        bit_depth (int): Bit depth of the imagery, necessary for proper normalization.
        defualts to 8 (standard for dra'd imagery).
        show_percentage (bool): Print percent of chips collected to stdout. Defaults
            to True
        assert_all_valid (bool): Throw an error if any of the included polygons do not
            match the size criteria (defined by min and max_side_dim), or are returned
            as None from geoio. Defaults to False.
        resize_dim (tup): Dimensions to reshape chips into after padding. Use for
            downsampling large chips. Dimensions: (n_chan, rows, cols). Defaults to
            None (does not resize).
        kwargs:
        -------
        bands (list of ints): The band numbers (base 1) to be retrieved from the
            imagery. Defualts to None (all bands retrieved)
        buffer (int or list of two ints): Number of pixels to add as a buffer around
            the requested pixels. If an int, the same number of pixels will be added
            to both dimensions. If a list of two ints, they will be interpreted as
            xpad and ypad.
    Returns
        chips (array): Uniformly sized chips with the following dimensions: (num_chips,
            num_channels, max_side_dim, max_side_dim)
        ids (list): Feature ids corresponding to chips.
        labels (array): One-hot encoded labels for chips with the follwoing dimensions:
            (num_chips, num_classes)
    '''

    def write_status(ct, chip_err=False):
        '''helper function to write percent complete to stdout + raise AssertionError'''
        if show_percentage:
            sys.stdout.write('\r%{0:.2f}'.format(100 * (ct + 1) / float(total)) + ' ' * 20)
            sys.stdout.flush()

        if chip_err and assert_all_valid:
            raise AssertionError('One or more invalid polygons. Please make sure all ' \
                                 'polygons are valid or set assert_all_valid to False.')
        return ct + 1

    ct, inputs, ids, imgs = 0, [], [], {}
    total = len(features) if not num_chips else num_chips

    if classes:
        labels, nb_classes = [],len(classes)
        cls_dict = {classes[i]: i for i in xrange(len(classes))}

    # cycle through polygons and get pixel data
    for poly in features:
        img_id = poly['properties']['image_id']
        coords = poly['geometry']['coordinates'][0]

        # open all images in geoio
        if img_id not in imgs.keys():
            try:
                imgs[img_id] = geoio.GeoImage(img_id + '.tif')
            except (ValueError):
                raise Exception('{}.tif not found in current directory. Please make ' \
                                'sure all images refereced in features are present and ' \
                                'named properly'.format(str(img_id)))

        # call get_data on polygon geom
        chip = imgs[img_id].get_data_from_coords(coords, mask=mask, **kwargs)
        if chip is None:
            ct = write_status(100 * ct / float(total), ct, chip_err=True)
            continue

        # check for adequate chip size
        chan, h, w = np.shape(chip)
        pad_h, pad_w = max_side_dim - h, max_side_dim - w

        if min(h, w) < min_side_dim or max(h, w) > max_side_dim:
            ct = write_status(ct, chip_err=True)
            continue

        # zero-pad polygons to (n_bands, max_side_dim, max_side_dim)
        chip = chip.filled(0).astype(float) if mask else chip
        chip_patch = np.pad(chip, [(0, 0), (pad_h/2, (pad_h - pad_h/2)), (pad_w/2,
                            (pad_w - pad_w/2))], 'constant', constant_values=0)

        # resize chip
        if resize_dim:
            new_chip = []
            for band_ix in xrange(len(chip_patch)):
                new_chip.append(imresize(chip_patch[band_ix],
                                resize_dim[-2:]).astype(float))
            chip_patch = np.array(new_chip)

        # norm pixel intenisty from 0 to 1
        if normalize:
            chip_patch /= float((2 ** bit_depth) - 1)

        # get labels
        if classes:
            try:
                label = poly['properties']['class_name']
                if label is None:
                    ct = write_status(ct, chip_err=True)
                    continue
                labels.append(cls_dict[label])

            except (TypeError, KeyError):
                ct = write_status(ct, chip_err=True)
                continue

        # get feature ids
        if return_id:
            feat_id = poly['properties']['feature_id']
            ids.append(feat_id)

        # append chip to inputs
        inputs.append(chip_patch)
        ct = write_status(ct)

        if num_chips:
            if len(inputs) == num_chips:
                break

    # combine data
    inputs = [np.array([i for i in inputs])]

    if return_id:
        inputs.append(ids)

    if classes:
        # format labels
        Y = np.zeros((len(labels), nb_classes))
        for i in range(len(labels)):
            Y[i, labels[i]] = 1
        inputs.append(Y)

    return inputs


def get_uniform_chips(input_file, num_chips=None, **kwargs):
    '''
    Get uniformly-sized pixel intensity arrays from image strips using a geojson file.
        Output will be in the same format as get_data_from_polygon_list.

    Args
        input_file (str): File name. This file should be filtered for polygon size
        num_chips (int): Maximum number of chips to return. If None will return all chips
            in input_file. Defaults to None
    kwargs:
    -------
        See get_data_from_polygon_list docstring for other input params

    Returns
        chips (array): Uniformly sized chips with the following dimensions: (num_chips,
            num_channels, max_side_dim, max_side_dim)
        ids (list): Feature ids corresponding to chips. Will only be present if
            return_ids is True
        labels (array): One-hot encoded labels for chips with the follwoing dimensions:
            (num_chips, num_classes). Will only be present if a classes parameter is
            passed
    '''

    # Load features from input_file
    with open(input_file) as f:
        feature_collection = geojson.load(f)['features']

    if num_chips:
        feature_collection = feature_collection[: num_chips]

    return get_data_from_polygon_list(feature_collection, num_chips=num_chips, **kwargs)


def uniform_chip_generator(input_file, batch_size=32, **kwargs):
    '''
    Generate batches of uniformly-sized pixel intensity arrays from image strips using a
        geojson file. Output will be in the same format as get_data_from_polygon_list.

    Args
        input_file (str): File name
        batch_size (int): Number of chips to yield per iteration
    kwargs:
    -------
        See get_data_from_polygon_list docstring for other input params. Do not use the
        num_chips arg.

    Returns
        chips (array): Uniformly sized chips with the following dimensions: (num_chips,
            num_channels, max_side_dim, max_side_dim)
        ids (list): Feature ids corresponding to chips. Will only be present if
            return_ids is True
        labels (array): One-hot encoded labels for chips with the follwoing dimensions:
            (num_chips, num_classes). Will only be present if a classes parameter is
            passed
    '''

    # Load features from input_file
    with open(input_file) as f:
        feature_collection = geojson.load(f)['features']

    # Produce batches using get_data_from_polygon_list
    for batch_ix in range(0, len(feature_collection), batch_size):
        this_batch = feature_collection[batch_ix: batch_ix + batch_size]

        yield get_data_from_polygon_list(this_batch, **kwargs)


def filter_polygon_size(input_file, output_file, min_side_dim=0, max_side_dim=125,
                        shuffle=False, make_omitted_files=False):
    '''
    Create a geojson file containing only polygons with acceptable side dimensions.
    INPUT   input_file (str): File name
            output_file (str): Name under which to save filtered polygons.
            min_side_dim (int): Minimum acceptable side length (in pixels) for
                each polygon. Defaults to 0.
            max_side_dim (int): Maximum acceptable side length (in pixels) for
                each polygon. Defaults to 125.
            shuffle (bool): Shuffle polygons before saving to output file. Defaults to
                False.
            make_omitted_files (bool): Create files with omitted polygons. Two files
                are created: one with polygons that are too small and one with large
                polygons. Defaults to False.
    '''

    def write_status(percent_complete):
        '''helper function to write percent complete to stdout'''
        sys.stdout.write('\r%{0:.2f}'.format(percent_complete) + ' ' * 20)
        sys.stdout.flush()

    # load polygons
    with open(input_file) as f:
        data = geojson.load(f)
        total_features = float(len(data['features']))

    # format output file name
    if not output_file.endswith('.geojson'):
        output_file += '.geojson'

    # find indicies of acceptable polygons
    ix_ok, small_ix, large_ix = [], [], []
    img_ids = gt.find_unique_values(input_file, property_name='image_id')

    print 'Filtering polygons... \n'
    for img_id in img_ids:
        ix = 0
        print '... for image {} \n'.format(img_id)
        img = geoio.GeoImage(img_id + '.tif')

        # create vrt if img has multiple bands (more efficient)
        if img.shape[0] > 1:
            vrt_flag = True
            subprocess.call('gdalbuildvrt tmp.vrt -b 1 {}.tif'.format(img_id), shell=True)
            img = geoio.GeoImage('tmp.vrt')

        # cycle thru polygons
        for chip, properties in img.iter_vector(vector=input_file,
                                                properties=True,
                                                filter=[{'image_id': img_id}],
                                                mask=True):
            ix += 1
            if chip is None:
                write_status(100 * ix / total_features)
                continue

            chan,h,w = np.shape(chip)

            # Identify small chips
            if min(h, w) < min_side_dim:
                small_ix.append(ix - 1)
                write_status(100 * ix / total_features)
                continue

            # Identify large chips
            elif max(h, w) > max_side_dim:
                large_ix.append(ix - 1)
                write_status(100 * ix / total_features)
                continue

            # Identify valid chips
            ix_ok.append(ix - 1)
            write_status(100 * ix / total_features)

        # remove vrt file
        if vrt_flag:
            os.remove('tmp.vrt')

    # save new geojson
    ok_polygons = [data['features'][i] for i in ix_ok]
    small_polygons = [data['features'][i] for i in small_ix]
    large_polygons = [data['features'][i] for i in large_ix]
    print str(len(small_polygons)) + ' small polygons removed'
    print str(len(large_polygons)) + ' large polygons removed'

    if shuffle:
        np.random.shuffle(ok_polygons)

    data['features'] = ok_polygons
    with open(output_file, 'wb') as f:
        geojson.dump(data, f)

    if make_omitted_files:
        # make file with small polygons
        data['features'] = small_polygons
        with open('small_' + output_file, 'w') as f:
            geojson.dump(data, f)

        # make file with large polygons
        data['features'] = large_polygons
        with open('large_' + output_file, 'w') as f:
            geojson.dump(data, f)

    print 'Saved {} polygons to {}'.format(str(len(ok_polygons)), output_file)
