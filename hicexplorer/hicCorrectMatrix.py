import sys, argparse
from scipy.sparse import lil_matrix
import logging

from hicexplorer.iterativeCorrection import iterativeCorrection
from hicexplorer import HiCMatrix as hm
from hicexplorer._version import __version__

import numpy as np
debug = 0


def parse_arguments(args=None):

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='Runs Dekker\'s iterative '
        'correction over a hic matrix.')

    # define the arguments
    parser.add_argument('--matrix', '-m',
                        help='Hi-C matrix.',
                        required=True)

    parser.add_argument('--iterNum', '-n',
                        help='number of iterations',
                        type=int,
                        metavar='INT',
                        default=500)

    parser.add_argument('--outFileName', '-o',
                        help='File name to save the resulting matrix. The '
                             'output is a .npz file.',
                        required=True)

    parser.add_argument('--poorRegionsCutoff', '-lowcut',
                        help='Poor regions are bins with low coverage. Those regions '
                        'considered  outliers in the low range are identified using '
                        'the MAD method. A usual cutoff is -1.2',
                        type=float)

    parser.add_argument('--inflationCutoff',
                        help='Value corresponding to the maximum number of times a bin '
                        'can be scaled up during the iterative correction. For example, '
                        'a inflation Cutoff of 3 will filter out all bins that were '
                        'expanded 3 times or more during the iterative correction.',
                        type=float)

    parser.add_argument('--transCutoff', '-transcut',
                        help='Clip high counts in the top -transcut trans '
                        'regions (i.e. between chromosomes). A usual value '
                        'is 0.05 ',
                        type=float)

    parser.add_argument('--sequencedCountCutoff', 
                        help='Each bin receives a value indicating the '
                        'fraction that is covered by reads. A cutoff of '
                        '0.5 will discard all those bins that have less '
                        'than half of the bin covered.',
                        default=None,
                        type=float)

    parser.add_argument('--chromosomes', 
                        help='List of chromosomes to be included in the iterative '
                        'correction. The order of the given chromosomes will be then ' 
                        'kept for the resulting corrected matrix',
                        default=None,
                        nargs='+')

    parser.add_argument('--skipDiagonal', '-s',
                        help='If set, diagonal counts are not included',
                        action='store_true')

    parser.add_argument('--perchr',
                        help='Normalize each chromosome separately',
                        action='store_true')

    parser.add_argument('--verbose',
                        help='Print processing status',
                        action='store_true')
    parser.add_argument('--version', action='version',
                        version='%(prog)s {}'.format(__version__))

    return parser


def iterative_correction(matrix, args):
    corrected_matrix, correction_factors = iterativeCorrection(matrix,
                                                               M=args.iterNum,
                                                               verbose=args.verbose)

    return corrected_matrix, correction_factors


def fill_gaps(hic_ma, failed_bins, fill_contiguous=False):
    """ try to fill-in the failed_bins the matrix by adding the
    average values of the neighboring rows and cols. The idea
    for the iterative correction is that is best to put
    something in contrast to not put anything

    hic_ma: hic matrix object
    failed_bins: list of bin ids
    fill_contiguous: If True, stretches of masked rows/cols are filled.
                     Otherwise, these cases are skipped

    """
    logging.info("starting fill gaps")
    mat_size = hic_ma.matrix.shape[0]
    fill_ma = hic_ma.matrix.copy().tolil()
    if fill_contiguous is True:
        discontinuous_failed = failed_bins
        consecutive_failed_idx = np.array([])
    else:
        # find stretches of consecutive failed regions
        consecutive_failed_idx = np.flatnonzero(np.diff(failed_bins) == 1)
        # the banned list of indices is equal to the actual list
        # and the list plus one, to identify consecutive failed regions.
        # for [1,2,5,10] the np.diff is [1,3,5]. The consecutive id list
        # is [0], for '1', in the original list, but we are missing the '2'
        # thats where the consecutive_failed_idx+1 comes.
        consecutive_failed_idx = np.unique(np.sort(
                np.concatenate([consecutive_failed_idx,
                                consecutive_failed_idx+1])))
        # find the failed regions that are not consecutive
        discontinuous_failed = [x for idx, x in enumerate(failed_bins)
                                if idx not in consecutive_failed_idx]

    sys.stderr.write("Filling {} failed bins\n".format(
            len(discontinuous_failed)))

    """
    for missing_bin in discontinuous_failed:
        if 0 < missing_bin < mat_size - 1:
            for idx in range(1, mat_size - 2):
                if idx % 100 == 0:
                    sys.stderr.write(".")
                # the new row value is the mean between the upper
                # and lower bins corresponding to the same diagonal
                fill_ma[missing_bin, idx :] = \
                    (hic_ma.matrix[missing_bin-1, idx-1] +
                     hic_ma.matrix[missing_bin+1, idx+1]) / 2

                # same for cols
                fill_ma[idx, missing_bin] = \
                    (hic_ma.matrix[idx-1, missing_bin-1] +
                     hic_ma.matrix[idx+1, missing_bin+1]) / 2

    """
    for missing_bin in discontinuous_failed:
        if 0 < missing_bin < mat_size - 1:
            # the new row value is the mean between the upper
            # and lower rows
            fill_ma[missing_bin, 1:mat_size-1] = \
                (hic_ma.matrix[missing_bin - 1, :mat_size-2] +
                 hic_ma.matrix[missing_bin + 1, 2:]) / 2

            # same for cols
            fill_ma[1:mat_size-1, missing_bin] = \
                (hic_ma.matrix[:mat_size-2, missing_bin - 1] +
                 hic_ma.matrix[2:, missing_bin + 1]) / 2

    # identify the intersection points of the failed regions because they
    # neighbors get wrong values
    for bin_a in discontinuous_failed:
        for bin_b in discontinuous_failed:
            if 0 < bin_a < mat_size and \
                    0 < bin_b < mat_size:
                # the fill value is the average over the
                # neighbors that do have a value

                fill_value = np.mean([
                        hic_ma.matrix[bin_a-1, bin_b-1],
                        hic_ma.matrix[bin_a-1, bin_b+1],
                        hic_ma.matrix[bin_a+1, bin_b-1],
                        hic_ma.matrix[bin_a+1, bin_b+1],
                        ])

                fill_ma[bin_a-1, bin_b] = fill_value
                fill_ma[bin_a+1, bin_b] = fill_value
                fill_ma[bin_a, bin_b-1] = fill_value
                fill_ma[bin_a, bin_b+1] = fill_value

    # return the matrix and the bins that continue to be failed regions
    return fill_ma.tocsr(), np.sort(failed_bins[consecutive_failed_idx])


def getPoorRegions(hic_ma, cutoff=-1.2):
    """
    The method is based on the median absolute deviation. See
    Boris Iglewicz and David Hoaglin (1993),
    "Volume 16: How to Detect and Handle Outliers",
    The ASQC Basic References in Quality Control:
    Statistical Techniques, Edward F. Mykytka, Ph.D., Editor.

    calls maskBins for the poor regions identified

    The method defines thresholds per chromosome
    to avoid introducing bias due to different chromosome numbers
    """
    # replace nan values by zero
    to_remove = []
    for chrname in hic_ma.interval_trees.keys():
        chr_range = hic_ma.getChrBinRange(chrname)
        chr_submatrix = hic_ma.matrix[chr_range[0]:chr_range[1],
                        chr_range[0]:chr_range[1]]

        chr_submatrix.data[np.isnan(chr_submatrix.data)] = 0
        row_sum = np.asarray(chr_submatrix.sum(axis=1)).flatten()
        # subtract from row sum, the diagonal
        # to account for interactions with other bins
        # and not only self interactions that are the dominant count
        row_sum = row_sum - chr_submatrix.diagonal()
        median = np.median(row_sum[row_sum > 0])
        b_value = 1.4826  # value for normal distribution
        mad = b_value * np.median(np.abs(row_sum-median))
        print("MAD value threshold for {}: {}, median: {}".format(chrname,
                                                                  mad, median))
        if mad > 0:
            deviation = (row_sum - median) / mad
            zero_deviation = np.mean(deviation[np.flatnonzero(row_sum == 0)])
            if zero_deviation > cutoff:
                sys.stderr.write("Warning. Cutoff too low. Bins with no "
                                 "counts have a deviation = {}"
                                 "\n".format(zero_deviation))
            problematic = np.flatnonzero(deviation <= cutoff)
            problematic += chr_range[0]
            to_remove.extend(problematic)

    return sorted(to_remove)


def main():
    args = parse_arguments().parse_args()
    ma = hm.hiCMatrix(args.matrix)
    if args.verbose:
        print "matrix contains {} data points. Sparsity {:.3f}.".format(
            len(ma.matrix.data),
            float(len(ma.matrix.data))/(ma.matrix.shape[0]**2))

    if args.chromosomes:
        ma.reorderChromosomes(args.chromosomes)

    if args.skipDiagonal:
        ma.diagflat(value=0)

    total_filtered_out = set()
    if hasattr(ma, "failed_bins"):
        total_filtered_out = set(ma.failed_bins)
        ma.printchrtoremove(ma.failed_bins, label="Failed bins")

    if args.sequencedCountCutoff and 0 < args.sequencedCountCutoff < 1:
        chrom, _, _, coverage = zip(*ma.cut_intervals)

        assert type(coverage[0]) == np.float64

        failed_bins = np.flatnonzero(
            np.array(coverage) < args.sequencedCountCutoff)

        ma.printchrtoremove(failed_bins, label="Bins with low coverage")
        ma.maskBins(failed_bins)
        total_filtered_out = set(failed_bins)
        """
        ma.matrix, to_remove = fill_gaps(ma, failed_bins)
        sys.stderr.write("From {} failed bins, {} could "
                         "not be filled\n".format(len(failed_bins),
                                                  len(to_remove)))
        ma.maskBins(to_remove)
        """

    """
    OBSOLETE
    addPseudocount = False
    if addPseudocount is True:
        sys.stderr.write("WARNING, adding pseudocount to diagonals close "
                   "to main diagonal\n")
        from scipy.sparse import dia_matrix
        data = np.array([np.zeros(ma.matrix.shape[0])]).repeat(201, axis=0) + 0.5
        ma.matrix = ma.matrix + dia_matrix((data, range(-100,101)),
                                            shape=ma.matrix.shape)

    """
    if args.poorRegionsCutoff: 
        poor_regions = getPoorRegions(ma, cutoff=args.poorRegionsCutoff)
        pct_poor = 100 * float(len(poor_regions)) / ma.matrix.shape[0]
        ma.printchrtoremove(poor_regions, label="Bins that are MAD outliers ({:.2f}%)".format(pct_poor))
        ma.maskBins(poor_regions)
        total_filtered_out = total_filtered_out.union(poor_regions)
    """
    The following code is obsolete and only kept for reference

    if args.poorRegionsCutoff:
        poor_regions = ma.maskPoorRegions(cutoff=args.poorRegionsCutoff)
        ma.printchrtoremove(poor_regions)


    if args.poorRegionsCutoff and args.poorRegionsCutoff > 0 and \
            args.poorRegionsCutoff < 100:
        ma.removePoorRegions(cutoff=args.poorRegionsCutoff)
    """

    if args.transCutoff and 0 < args.transCutoff < 100:
        cutoff = float(args.transCutoff)/100
        # a usual cutoff is 0.05 
        ma.truncTrans(high=cutoff)

    pre_row_sum = np.asarray(ma.matrix.sum(axis=1)).flatten()
    correction_factors = []
    if args.perchr:
        corrected_matrix = lil_matrix(ma.matrix.shape)
        # normalize each chromosome independently
        for chrname in ma.interval_trees.keys():
            chr_range = ma.getChrBinRange(chrname)
            chr_submatrix = ma.matrix[chr_range[0]:chr_range[1], chr_range[0]:chr_range[1]]
            _matrix, _corr_factors = iterative_correction(chr_submatrix, args)
            corrected_matrix[chr_range[0]:chr_range[1], chr_range[0]:chr_range[1]] = _matrix
            correction_factors.append(_corr_factors)
        correction_factors = np.concatenate(correction_factors)

    else:
        corrected_matrix, correction_factors = iterative_correction(ma.matrix, args)

    ma.setMatrixValues(corrected_matrix)
    ma.setCorrectionFactors(correction_factors)
    if args.inflationCutoff and args.inflationCutoff > 0:
        after_row_sum = np.asarray(corrected_matrix.sum(axis=1)).flatten()
        # identify rows that were expanded more than args.inflationCutoff times
        to_remove = np.flatnonzero(after_row_sum / pre_row_sum >= args.inflationCutoff)
        ma.printchrtoremove(to_remove,
                            label="inflated >={} "
                            "regions".format(args.inflationCutoff))
        total_filtered_out = total_filtered_out.union(to_remove)

        ma.maskBins(to_remove)

    ma.printchrtoremove(sorted(list(total_filtered_out)),
                        label="Total regions to be removed")

    ma.save(args.outFileName)
