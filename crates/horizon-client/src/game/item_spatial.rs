// Spatial candidate set for villager sensing, preserving original Vec order.
// Safe 3D grid of item *centres*. The caller must apply the unchanged
// bounding-box, distance, pickup, inventory and tie-breaking predicates.
// Returned indices are sorted in original Vec order, never hash order.
use std::collections::HashMap;

const SIDE: f64 = 32.0;
const MAX_QUERY_CELLS: i64 = 4096;

pub(crate) struct ItemSpatialIndex {
    cells: HashMap<(i32, i32, i32), Vec<usize>>,
    exceptional: Vec<usize>,
    len: usize,
}

impl ItemSpatialIndex {
    /// Cheap estimate to keep tiny or crowded scenes on the original scan.
    /// Samples up to 33 positions; only spatially spread scenes use the grid.
    pub(crate) fn worthwhile(
        points: impl ExactSizeIterator<Item = [f64; 3]>,
        queries: usize,
    ) -> bool {
        let len = points.len();
        if len < 2048 || queries < 32 {
            return false;
        }
        let stride = (len / 32).max(1);
        let mut distinct = std::collections::HashSet::new();
        for (i, p) in points.enumerate() {
            if i % stride == 0 && p.iter().all(|v| v.is_finite()) {
                distinct.insert((cell(p[0]), cell(p[2])));
                if distinct.len() >= 9 {
                    return true;
                }
            }
        }
        false
    }

    pub(crate) fn build(points: impl IntoIterator<Item = [f64; 3]>) -> Self {
        let mut index = Self {
            cells: HashMap::new(),
            exceptional: Vec::new(),
            len: 0,
        };
        for p in points {
            let i = index.len;
            index.len += 1;
            if p.iter().all(|v| {
                v.is_finite() && (*v / SIDE) >= i32::MIN as f64 && (*v / SIDE) < i32::MAX as f64
            }) {
                let key = (cell(p[0]), cell(p[1]), cell(p[2]));
                index.cells.entry(key).or_default().push(i);
            } else {
                // Unusual coordinates must still pass the old exact filter.
                index.exceptional.push(i);
            }
        }
        index
    }

    pub(crate) fn candidates(&self, min: [f64; 3], max: [f64; 3]) -> Vec<usize> {
        let finite = min.iter().chain(max.iter()).all(|v| {
            v.is_finite() && (*v / SIDE) >= i32::MIN as f64 && (*v / SIDE) < i32::MAX as f64
        });
        if !finite || (0..3).any(|d| min[d] > max[d]) {
            return (0..self.len).collect();
        }
        let lo = [cell(min[0]), cell(min[1]), cell(min[2])];
        let hi = [cell(max[0]), cell(max[1]), cell(max[2])];
        let mut count = 1i64;
        for d in 0..3 {
            count = count.saturating_mul((hi[d] as i64 - lo[d] as i64 + 1).max(0));
        }
        if count > MAX_QUERY_CELLS {
            return (0..self.len).collect();
        }
        let mut out = Vec::new();
        for x in lo[0]..=hi[0] {
            for y in lo[1]..=hi[1] {
                for z in lo[2]..=hi[2] {
                    if let Some(v) = self.cells.get(&(x, y, z)) {
                        out.extend(v.iter().copied());
                    }
                }
            }
        }
        out.extend(self.exceptional.iter().copied());
        out.sort_unstable();
        out
    }
}

pub(crate) enum ItemCandidates {
    All(std::ops::Range<usize>),
    Indexed(std::vec::IntoIter<usize>),
}

impl Iterator for ItemCandidates {
    type Item = usize;
    fn next(&mut self) -> Option<Self::Item> {
        match self {
            ItemCandidates::All(iter) => iter.next(),
            ItemCandidates::Indexed(iter) => iter.next(),
        }
    }
}

impl ItemSpatialIndex {
    /// Same order as original enumerate(), using a zero-allocation fallback.
    pub(crate) fn iter(
        index: Option<&Self>,
        item_count: usize,
        min: [f64; 3],
        max: [f64; 3],
    ) -> ItemCandidates {
        match index {
            Some(idx) => ItemCandidates::Indexed(idx.candidates(min, max).into_iter()),
            None => ItemCandidates::All(0..item_count),
        }
    }
}

fn cell(v: f64) -> i32 {
    (v / SIDE).floor() as i32
}
