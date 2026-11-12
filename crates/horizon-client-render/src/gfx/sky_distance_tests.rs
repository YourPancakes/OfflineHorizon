//! Execute the production WGSL distance function against the previous shader.
use wgpu::util::DeviceExt;

#[test]
fn sky_octagon_gpu_matches_previous_distance() {
    let instance = super::test_gpu::instance();
    let adapter = pollster::block_on(instance.request_adapter(&Default::default()))
        .expect("GPU required for sky proof");
    eprintln!("sky proof adapter: {:?}", adapter.get_info());
    let (device, queue) = pollster::block_on(adapter.request_device(&Default::default())).unwrap();
    let source = include_str!("../terrain.wgsl");
    let start = source.find("fn disc_distance(").unwrap();
    let open = start + source[start..].find('{').unwrap();
    let mut depth = 1;
    let mut end = open + 1;
    while depth > 0 {
        match source.as_bytes()[end] {
            b'{' => depth += 1,
            b'}' => depth -= 1,
            _ => {}
        }
        end += 1;
    }
    let previous = r#"
const PI: f32 = 3.14159265;
fn previous_distance(d: vec3<f32>, y: f32) -> vec2<f32> {
    if d.y * y <= 0.0 { return vec2(-1.0); }
    let p = d * (y / d.y);
    let h = length(p.xz);
    let phi = atan2(p.z, p.x);
    let sector = PI / 4.0;
    let delta = phi - (floor(phi / sector) * sector + sector * 0.5);
    let edge = 512.0 * cos(sector * 0.5) / cos(delta);
    if h > edge { return vec2(-1.0); }
    let s = h / edge;
    let ay = abs(y);
    let rim = sqrt(512.0 * 512.0 + y * y);
    return vec2(ay + s * (rim - ay), ay + s * (512.0 - ay));
}
@group(0) @binding(0) var<storage, read> cases: array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> results: array<vec4<f32>>;
@compute @workgroup_size(64)
fn compare(@builtin(global_invocation_id) id: vec3<u32>) {
    if id.x >= arrayLength(&cases) { return; }
    let c = cases[id.x];
    results[id.x] = vec4(disc_distance(c.xyz, c.w), previous_distance(c.xyz, c.w));
}
"#;
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("production and previous sky distance"),
        source: wgpu::ShaderSource::Wgsl((source[start..end].to_owned() + previous).into()),
    });
    let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: None,
        layout: None,
        module: &shader,
        entry_point: Some("compare"),
        compilation_options: Default::default(),
        cache: None,
    });
    let mut cases = Vec::<[f32; 4]>::new();
    for y in [-16.0_f32, 16.0] {
        for i in 0..1024 {
            let angle = i as f32 * std::f32::consts::TAU / 1024.0;
            for radius in [0.0, 128.0, 400.0, 473.0, 500.0, 511.0, 512.5, 600.0] {
                for scale in [1.0, 1e-6] {
                    cases.push([
                        radius * angle.cos() * scale,
                        y * scale,
                        radius * angle.sin() * scale,
                        y,
                    ]);
                }
            }
        }
        cases.push([1.0, -y, 1.0, y]);
        cases.push([1.0, 0.0, 1.0, y]);
    }
    let input = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytemuck::cast_slice(&cases),
        usage: wgpu::BufferUsages::STORAGE,
    });
    let size = (cases.len() * 16) as u64;
    let output = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    let read = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &pipeline.get_bind_group_layout(0),
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: input.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: output.as_entire_binding(),
            },
        ],
    });
    let mut encoder = device.create_command_encoder(&Default::default());
    {
        let mut pass = encoder.begin_compute_pass(&Default::default());
        pass.set_pipeline(&pipeline);
        pass.set_bind_group(0, &group, &[]);
        pass.dispatch_workgroups((cases.len() as u32).div_ceil(64), 1, 1);
    }
    encoder.copy_buffer_to_buffer(&output, 0, &read, 0, size);
    queue.submit([encoder.finish()]);
    read.slice(..).map_async(wgpu::MapMode::Read, |_| {});
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    let bytes = read.slice(..).get_mapped_range().unwrap();
    let results: &[[f32; 4]] = bytemuck::cast_slice(&bytes);
    let mut max_error = 0.0_f32;
    for (case, result) in cases.iter().zip(results) {
        let [x, y, previous_x, previous_y] = *result;
        assert_eq!(x < 0.0, previous_x < 0.0, "hit classification at {case:?}");
        for error in [(x - previous_x).abs(), (y - previous_y).abs()] {
            assert!(error <= 0.002, "distance error {error} at {case:?}");
            max_error = max_error.max(error);
        }
    }
    eprintln!(
        "sky GPU proof: {} cases; maximum distance error {max_error}",
        cases.len()
    );
}
