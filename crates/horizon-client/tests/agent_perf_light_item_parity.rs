//! Uses genuine horizon-client streaming trait, ItemEntity.bounds,
//! horizon-core Aabb geometry, and the exact integrated index module.
//! The full Game/Villager state is not constructed here.
use horizon_client::{
    chunk::Chunk,
    entities::ItemEntity,
    items::ItemStack,
    streaming::{ChunkGenerator, Proto},
};
use horizon_core::geometry::{Aabb, Vec3};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
#[path = "../src/game/item_spatial.rs"]
mod actual_index;
use actual_index::ItemSpatialIndex;

struct RealTraitDefault(Arc<AtomicUsize>);
impl ChunkGenerator for RealTraitDefault {
    type Worker = ();
    fn worker(&self) -> Self::Worker {}
    fn proto(&self, _worker: &mut (), _x: i32, _z: i32) -> Proto {
        Box::new(false)
    }
    fn finish(&self, _: Proto) -> Chunk {
        Chunk::empty(0, 0)
    }
    fn light_view(&self, proto: &Proto) -> Option<Chunk> {
        self.0.fetch_add(1, Ordering::Relaxed);
        proto
            .downcast_ref::<bool>()
            .filter(|ready| **ready)
            .map(|_| Chunk::empty(0, 0))
    }
}
struct RealTraitOptimized(Arc<AtomicUsize>);
impl ChunkGenerator for RealTraitOptimized {
    type Worker = ();
    fn worker(&self) -> Self::Worker {}
    fn proto(&self, _worker: &mut (), _x: i32, _z: i32) -> Proto {
        Box::new(false)
    }
    fn finish(&self, _: Proto) -> Chunk {
        Chunk::empty(0, 0)
    }
    fn light_view(&self, proto: &Proto) -> Option<Chunk> {
        self.0.fetch_add(1, Ordering::Relaxed);
        proto
            .downcast_ref::<bool>()
            .filter(|ready| **ready)
            .map(|_| Chunk::empty(0, 0))
    }
    fn light_view_ready(&self, proto: &Proto) -> bool {
        proto.downcast_ref::<bool>().copied() == Some(true)
    }
}
#[test]
fn actual_chunk_generator_trait_default_preserves_lookup() {
    let calls = Arc::new(AtomicUsize::new(0));
    let generator = RealTraitDefault(calls.clone());
    for p in [
        Box::new(true) as Proto,
        Box::new(false) as Proto,
        Box::new(0u64) as Proto,
    ] {
        let before = generator.light_view(&p).is_some();
        let after = generator.light_view_ready(&p);
        assert_eq!(before, after);
    }
    assert_eq!(
        calls.load(Ordering::Relaxed),
        6,
        "default delegates original"
    );
}
#[test]
fn actual_trait_opt_in_can_avoid_repacking() {
    let calls = Arc::new(AtomicUsize::new(0));
    let generator = RealTraitOptimized(calls.clone());
    for p in [
        Box::new(true) as Proto,
        Box::new(false) as Proto,
        Box::new(0u64) as Proto,
    ] {
        let before = generator.light_view(&p).is_some();
        let after = generator.light_view_ready(&p);
        assert_eq!(before, after);
    }
    assert_eq!(
        calls.load(Ordering::Relaxed),
        3,
        "ready should not make a column"
    );
}

fn item(id: u32, p: Vec3) -> ItemEntity {
    ItemEntity {
        health: 5,
        fire_ticks: 0,
        id,
        stack: ItemStack {
            item: Arc::from("minecraft:stone"),
            count: 1,
            damage: 0,
            extra: None,
        },
        thrower: None,
        target: None,
        position: p,
        previous: p,
        velocity: Vec3::new(0., 0., 0.),
        on_ground: false,
        age: 0,
        pickup_delay: 0,
        bob_offset: 0.,
        ticks: 0,
    }
}
fn distance2(a: Vec3, b: Vec3) -> f64 {
    a.distance_squared(b)
}
fn candidate_bounds(area: Aabb) -> ([f64; 3], [f64; 3]) {
    let (lo, hi) = (area.min_position(), area.max_position());
    (
        [lo.x - 0.125, lo.y - 0.25, lo.z - 0.125],
        [hi.x + 0.125, hi.y, hi.z + 0.125],
    )
}
fn check(items: &[ItemEntity], at: Vec3, area: Aabb) {
    let idx = ItemSpatialIndex::build(
        items
            .iter()
            .map(|e| [e.position.x, e.position.y, e.position.z]),
    );
    let (min, max) = candidate_bounds(area);
    let a: Vec<usize> = items
        .iter()
        .enumerate()
        .filter_map(|(i, e)| {
            (e.bounds().intersects(area) && distance2(e.position, at) < 1024.).then_some(i)
        })
        .collect();
    let b: Vec<usize> = ItemSpatialIndex::iter(Some(&idx), items.len(), min, max)
        .filter(|&i| items[i].bounds().intersects(area) && distance2(items[i].position, at) < 1024.)
        .collect();
    assert_eq!(a, b, "same item indexes and exact order");
    let scan: Vec<usize> = ItemSpatialIndex::iter(None, items.len(), min, max).collect();
    assert_eq!(
        scan,
        (0..items.len()).collect::<Vec<_>>(),
        "fallback matches original Vec"
    );
}
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }
    fn f(&mut self, spread: i64) -> f64 {
        let n = (self.next() % (2 * spread + 1) as u64) as i64 - spread;
        n as f64 + (self.next() % 1024) as f64 / 1024.
    }
}
#[test]
fn actual_item_entity_bounds_and_real_aabb_candidates_equal() {
    let mut r = Rng(0xABCDEFDEADBEEF);
    let mut checks = 0;
    for radius in [1.0, 4.0, 12.0, 32.0] {
        for _ in 0..300 {
            let center = Vec3::new(r.f(200), r.f(50), r.f(200));
            let area = Aabb::new(
                Vec3::new(center.x - radius, center.y - 16., center.z - radius),
                Vec3::new(center.x + radius, center.y + 16., center.z + radius),
            );
            let mut items = (0..160)
                .map(|j| {
                    let p = Vec3::new(r.f(400), r.f(100), r.f(400));
                    item(j, p)
                })
                .collect::<Vec<_>>();
            items.push(item(9001, center));
            items.push(item(
                9002,
                Vec3::new(center.x + radius + 0.125, center.y, center.z),
            ));
            items.push(item(9003, Vec3::new(f64::NAN, 1., 1.)));
            items.push(item(9004, Vec3::new(f64::INFINITY, 1., 1.)));
            check(&items, center, area);
            checks += 1;
        }
    }
    // Ensure the indexed branch is permitted in the actual heuristic
    // and retains all qualifying Vec entries even at 2500+ items.
    let items = (0..2600)
        .map(|j| {
            item(
                j,
                Vec3::new(
                    (j % 51) as f64 * 32.,
                    (j % 11) as f64 * 5.,
                    (j / 51) as f64 * 33.,
                ),
            )
        })
        .collect::<Vec<_>>();
    assert!(ItemSpatialIndex::worthwhile(
        items
            .iter()
            .map(|e| [e.position.x, e.position.y, e.position.z]),
        55
    ));
    for x in [0., 64., 256., 512., 960., 1536.] {
        let at = Vec3::new(x, 30., x);
        let area = Aabb::new(
            Vec3::new(at.x - 32., at.y - 16., at.z - 32.),
            Vec3::new(at.x + 32., at.y + 16., at.z + 32.),
        );
        check(&items, at, area);
        checks += 1;
    }
    println!("PASS {checks} checks with actual ItemEntity.bounds and Aabb.intersects");
}
