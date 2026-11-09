"""
MTO2 (Max-Tree Object Representation & Deblending) Masking Module.

Implements astronomical source detection and deblending based on semantically-informed
max-trees (Teeninga et al. 2016, Faezi et al. 2024 / MTO2: https://github.com/m-faezi/MTO2).

This module segments astronomical sources in star stamp cutouts (or residual maps)
and selectively masks sources that are NOT the main star stamp, while strictly
preserving the main star core and its 24 diffraction spikes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import logging
import numpy as np
from scipy.ndimage import gaussian_filter, binary_dilation
from scipy.stats import chi2
from astropy.stats import sigma_clipped_stats

try:
    import higra as hg
except ImportError:
    hg = None

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger("romanepsf.mto2")


@dataclass
class MTO2Config:
    """Configuration for MTO2 max-tree source segmentation and masking."""
    s_sigma: float = 1.6
    alpha: float = 1e-6
    move_factor: float = 0.1
    area_ratio: float = 0.90
    dilation_px: int = 2
    min_source_area_px: int = 3
    background_mode: str = "const"


def estimate_local_background(
    image: np.ndarray,
    mask: Optional[np.ndarray] = None,
) -> Tuple[float, float, float]:
    """
    Robustly estimate local background mean, variance, and effective gain
    from valid, unmasked pixels of a stamp.

    Parameters
    ----------
    image : np.ndarray
        2D image or stamp array.
    mask : np.ndarray, optional
        Mask of bad or saturated pixels to exclude (True = exclude).

    Returns
    -------
    Tuple[float, float, float]
        (bg_mean, bg_var, bg_gain)
    """
    valid = np.isfinite(image)
    if mask is not None:
        valid &= (~mask)

    if np.count_nonzero(valid) < 10:
        return 0.0, 1.0, 1.0

    valid_vals = image[valid]
    try:
        _, bg_med, bg_std = sigma_clipped_stats(valid_vals, sigma=3.0, maxiters=5)
    except Exception:
        bg_med = float(np.nanmedian(valid_vals))
        bg_std = float(np.nanstd(valid_vals))

    bg_med = float(bg_med) if np.isfinite(bg_med) else 0.0
    bg_std = float(bg_std) if np.isfinite(bg_std) and bg_std > 0 else 1.0
    bg_var = max(bg_std**2, 1e-6)

    # Estimate soft bias and effective gain
    min_val = float(np.nanmin(valid_vals))
    soft_bias = min(min_val, 0.0)
    bg_gain = (bg_med - soft_bias) / bg_var if bg_var > 0 and (bg_med - soft_bias) > 0 else 1.0
    bg_gain = max(float(bg_gain), 1e-4)

    return bg_med, bg_var, bg_gain


def compute_tree_power(
    tree: Any,
    altitudes: np.ndarray,
    image_normalized: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute node area and exact power statistic according to Teeninga et al. (2016).

    Formula:
        P(n) = sum_{x in n} (I(x) - alt_{p(n)})^2
             = sum_x(I^2) + area * alt_{p(n)}^2 - 2 * alt_{p(n)} * sum_x(I)
    """
    area = np.asarray(hg.attribute_area(tree)).astype(np.int32, copy=False)
    sum_vals = np.asarray(hg.accumulate_sequential(tree, image_normalized, hg.Accumulators.sum)).astype(np.float32, copy=False)
    sum_vals2 = np.asarray(hg.accumulate_sequential(tree, image_normalized * image_normalized, hg.Accumulators.sum)).astype(np.float32, copy=False)

    parents = tree.parents()
    parent_altitudes = altitudes[parents]
    power = sum_vals2 + area * (parent_altitudes**2) - 2.0 * parent_altitudes * sum_vals
    return area, power


def segment_sources_mto2(
    image: np.ndarray,
    s_sigma: float = 1.6,
    alpha: float = 1e-6,
    move_factor: float = 0.1,
    area_ratio: float = 0.90,
    bg_mean: Optional[float] = None,
    bg_var: Optional[float] = None,
    bg_gain: Optional[float] = None,
    dq_mask: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Dict[int, Dict[str, Any]]]:
    """
    Segment astronomical sources using MTO2 semantically-informed Max-Trees.

    Parameters
    ----------
    image : np.ndarray
        2D input array (stamp flux or residual map).
    s_sigma : float, default 1.6
        Gaussian smoothing kernel standard deviation to suppress pixel-scale noise.
    alpha : float, default 1e-6
        Significance level for the Chi-Square statistical test against Poisson+Gaussian noise.
    move_factor : float, default 0.1
        Factor for adjusting object boundaries based on local noise (0 = omit move_up).
    area_ratio : float, default 0.90
        Deblending sensitivity ratio for hierarchical tree node splitting.
    bg_mean : float, optional
        Pre-computed background mean. If None, estimated via sigma-clipped stats.
    bg_var : float, optional
        Pre-computed background variance. If None, estimated via sigma-clipped stats.
    bg_gain : float, optional
        Pre-computed effective gain (e-/flux unit). If None, estimated from data.
    dq_mask : np.ndarray, optional
        Mask of bad or saturated pixels.

    Returns
    -------
    Tuple[np.ndarray, Dict[int, Dict[str, Any]]]
        seg_map : int32 array where 0 is background and positive integers are unique object IDs.
        catalog : dict mapping object_id -> {'area': int, 'centroid_xy': (float, float), 'peak_flux': float}
    """
    if hg is None:
        raise ImportError(
            "higra is required for MTO2 source segmentation. Please install it with 'pip install higra'."
        )

    clean_img = np.array(image, dtype=np.float32, copy=True)
    nan_mask = ~np.isfinite(clean_img)
    if dq_mask is not None:
        nan_mask |= dq_mask

    # Background estimation
    if bg_mean is None or bg_var is None or bg_gain is None:
        est_mean, est_var, est_gain = estimate_local_background(clean_img, mask=nan_mask)
        if bg_mean is None:
            bg_mean = est_mean
        if bg_var is None:
            bg_var = est_var
        if bg_gain is None:
            bg_gain = est_gain

    # Impute NaNs with background level for tree construction
    clean_img[nan_mask] = float(bg_mean)

    # 1. Gaussian smoothing
    smooth_img = gaussian_filter(clean_img, sigma=s_sigma) if s_sigma > 0 else clean_img
    im_normalized = np.clip(smooth_img - float(bg_mean), a_min=0.0, a_max=None)

    # 2. Construct 8-adjacency Max-Tree
    graph = hg.get_8_adjacency_graph(im_normalized.shape)
    tree, altitudes = hg.component_tree_max_tree(graph, im_normalized)

    parents = tree.parents()
    area, power = compute_tree_power(tree, altitudes, im_normalized)
    parent_area = area[parents]

    # 3. Statistical significance test (Poisson + Gaussian local noise variance)
    parent_altitudes = altitudes[parents]
    denominator = float(bg_var) + np.maximum(0.0, parent_altitudes) / max(float(bg_gain), 1e-6)
    safe_denominator = np.where(denominator <= 0.0, 1e-6, denominator)
    norm_power = power / safe_denominator

    # Evaluate significance against Chi-Square upper quantile
    prob_p = max(min(1.0 - alpha, 1.0 - 1e-12), 1e-12)
    crit_val = chi2.ppf(prob_p, np.maximum(area, 1))
    significant_nodes = (norm_power > crit_val)
    significant_nodes[:tree.num_leaves()] = False

    if not np.any(significant_nodes):
        # No significant objects found above background noise
        return np.zeros(image.shape, dtype=np.int32), {}

    # 4. Deblending & Object selection via main branch analysis
    filtered_tree, node_map = hg.simplify_tree(tree, ~significant_nodes)
    largest_child = hg.accumulate_parallel(filtered_tree, area[node_map], hg.Accumulators.argmax)
    child_number = hg.attribute_child_number(filtered_tree)
    main_branch_local = (child_number == largest_child[filtered_tree.parents()])

    root_children = filtered_tree.children(filtered_tree.root())
    main_branch_local[root_children] = False

    is_obj = np.logical_not(main_branch_local) & significant_nodes[node_map] & (area[node_map] >= 3)
    init_segments = np.zeros(tree.num_vertices(), dtype=bool)
    init_segments[node_map[is_obj]] = True

    # 5. Boundary refinement (move_up)
    if move_factor > 0 and np.any(init_segments):
        largest_child_orig = hg.accumulate_parallel(tree, area, hg.Accumulators.argmax)
        main_branch_orig = (hg.attribute_child_number(tree) == largest_child_orig[tree.parents()])
        closest_object_ancestor = hg.propagate_sequential(
            tree,
            np.arange(tree.num_vertices()),
            np.logical_and(main_branch_orig, np.logical_not(init_segments)),
        )

        target_altitudes = altitudes.copy()
        object_indexes, = np.nonzero(init_segments)
        local_noise = np.sqrt(
            np.maximum(0.0, (float(bg_var) + altitudes[tree.parent(object_indexes)]) / max(float(bg_gain), 1e-6))
        )
        target_altitudes[object_indexes] = altitudes[object_indexes] + abs(move_factor * local_noise)
        target_altitudes = target_altitudes[closest_object_ancestor]

        valid_moves = np.logical_and(
            altitudes >= target_altitudes,
            np.logical_and(
                init_segments[closest_object_ancestor],
                area / np.maximum(parent_area, 1) >= area_ratio,
            ),
        )
        corrected_segments = np.logical_and(
            valid_moves,
            np.logical_or(
                closest_object_ancestor == tree.parents(),
                np.logical_not(valid_moves[tree.parents()]),
            ),
        )
    else:
        corrected_segments = init_segments

    # 6. Reconstruct segmentation map
    tree_of_segments, _ = hg.simplify_tree(tree, ~corrected_segments)
    unique_segment_ids = np.arange(tree_of_segments.num_vertices(), dtype=np.int32)[::-1]
    unique_segment_ids[tree_of_segments.root()] = 0
    seg_map = hg.reconstruct_leaf_data(tree_of_segments, unique_segment_ids).astype(np.int32)

    # 7. Compute object catalog metadata
    catalog: Dict[int, Dict[str, Any]] = {}
    obj_ids = [int(i) for i in np.unique(seg_map) if i != 0]

    for sid in obj_ids:
        coords = np.argwhere(seg_map == sid)
        if len(coords) == 0:
            continue
        cy_s, cx_s = np.mean(coords, axis=0)
        pix_vals = image[coords[:, 0], coords[:, 1]]
        valid_pix = pix_vals[np.isfinite(pix_vals)]
        peak_f = float(np.max(valid_pix)) if len(valid_pix) > 0 else 0.0
        tot_f = float(np.sum(valid_pix)) if len(valid_pix) > 0 else 0.0
        catalog[sid] = {
            "area": int(len(coords)),
            "centroid_xy": (float(cx_s), float(cy_s)),
            "peak_flux": peak_f,
            "total_flux": tot_f,
        }

    return seg_map, catalog


def mask_sources_not_main_star_mto2(
    stamp: np.ndarray,
    center_xy: Optional[Tuple[float, float]] = None,
    core_protection_radius_px: float = 6.0,
    dq_mask: Optional[np.ndarray] = None,
    protected_spikes: Optional[np.ndarray] = None,
    s_sigma: float = 1.6,
    alpha: float = 1e-6,
    move_factor: float = 0.1,
    area_ratio: float = 0.90,
    dilation_px: int = 2,
    apply_on_residual: bool = False,
    residual: Optional[np.ndarray] = None,
    min_source_area_px: int = 3,
) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """
    Mask sources that are NOT the main star stamp using MTO2 max-tree segmentation.

    Identifies which detected max-tree segments belong to the central main star
    (components overlapping the core or centered within core_protection_radius_px),
    and masks ALL other detected sources while strictly protecting the main star
    diffraction spikes and core.

    Parameters
    ----------
    stamp : np.ndarray
        2D stamp array of stellar flux.
    center_xy : Tuple[float, float], optional
        Centroid (x, y) of the primary star. If None, uses geometric center of stamp.
    core_protection_radius_px : float, default 6.0
        Radius in pixels around center_xy defining the central stellar core.
    dq_mask : np.ndarray, optional
        Pre-existing bad pixel / DQ mask (True = bad).
    protected_spikes : np.ndarray, optional
        Binary mask of Roman 24 diffraction spikes to protect from false-positive masking.
    s_sigma : float, default 1.6
        Smoothing scale for MTO2 max-tree construction.
    alpha : float, default 1e-6
        Significance level for Chi-Square attribute testing.
    move_factor : float, default 0.1
        MTO2 isophote boundary growth factor.
    area_ratio : float, default 0.90
        Deblending sensitivity ratio.
    dilation_px : int, default 2
        Morphological dilation radius to capture contaminant outskirts.
    apply_on_residual : bool, default False
        If True and residual is provided, runs MTO2 on the residual rather than raw stamp.
    residual : np.ndarray, optional
        Residual map (stamp - model) if available.
    min_source_area_px : int, default 3
        Minimum pixel count for a non-star source to be masked.

    Returns
    -------
    Tuple[np.ndarray, np.ndarray, List[int]]
        final_mask : bool[H, W] indicating masked pixels (contaminants + dq + nans, spikes protected).
        seg_map : int32[H, W] full MTO2 segmentation map.
        main_star_ids : List[int] segment IDs attributed to the main star.
    """
    ny, nx = stamp.shape
    if center_xy is None:
        cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    else:
        cx, cy = float(center_xy[0]), float(center_xy[1])

    grid_y, grid_x = np.ogrid[:ny, :nx]
    dist_from_center = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)
    core_zone = (dist_from_center <= core_protection_radius_px)

    # Choose image to segment
    seg_target = stamp
    if apply_on_residual and residual is not None:
        seg_target = residual

    # Run MTO2 segmentation
    seg_map, catalog = segment_sources_mto2(
        seg_target,
        s_sigma=s_sigma,
        alpha=alpha,
        move_factor=move_factor,
        area_ratio=area_ratio,
        dq_mask=dq_mask,
    )

    # Identify main star segment IDs:
    # RULE: In MTO objects, remove from mask all IDs that overlap with the protected center,
    # not only that region but the ENTIRE region covered by each such ID.
    main_star_ids: List[int] = []

    # 1. Any segment that has ANY pixel overlapping core_zone (r <= core_protection_radius_px)
    for sid in catalog.keys():
        obj_pixels = (seg_map == sid)
        if np.any(obj_pixels & core_zone):
            if sid not in main_star_ids:
                main_star_ids.append(sid)

    # 2. Also check if the central coordinate pixel has a label
    central_id = int(seg_map[int(round(cy)), int(round(cx))])
    if central_id != 0 and central_id not in main_star_ids:
        main_star_ids.append(central_id)

    # Non-main-star source IDs are all remaining non-zero segments with area >= min_source_area_px
    other_source_ids = [
        sid for sid in catalog.keys()
        if sid not in main_star_ids and catalog[sid]["area"] >= min_source_area_px
    ]

    # Create contaminant mask
    if len(other_source_ids) > 0:
        contam_raw = np.isin(seg_map, other_source_ids)
    else:
        contam_raw = np.zeros(stamp.shape, dtype=bool)

    # Optional morphological dilation
    if dilation_px > 0 and np.any(contam_raw):
        if cv2 is not None:
            ksize = 2 * int(dilation_px) + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
            contam_dilated = cv2.dilate(contam_raw.astype(np.uint8), kernel, iterations=1).astype(bool)
        else:
            struct = np.ones((2 * int(dilation_px) + 1, 2 * int(dilation_px) + 1), dtype=bool)
            contam_dilated = binary_dilation(contam_raw, structure=struct, iterations=1)
    else:
        contam_dilated = contam_raw.copy()

    # STRICT INVARIANT: Remove from mask all IDs that overlap with the protected center:
    # not only the core_zone circle, but the ENTIRE region covered by each such ID!
    for sid in main_star_ids:
        contam_dilated[seg_map == sid] = False

    contam_dilated[core_zone] = False
    if protected_spikes is not None:
        contam_dilated[protected_spikes > 0] = False

    # Assemble final mask: contaminants + dq_mask + NaNs
    final_mask = contam_dilated.copy()
    if dq_mask is not None:
        final_mask |= dq_mask
    final_mask |= (~np.isfinite(stamp))

    return final_mask, seg_map, main_star_ids


__all__ = [
    "MTO2Config",
    "estimate_local_background",
    "compute_tree_power",
    "segment_sources_mto2",
    "mask_sources_not_main_star_mto2",
]
