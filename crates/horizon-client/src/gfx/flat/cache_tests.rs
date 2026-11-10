use super::*;
use wgpu::util::DeviceExt;

fn render_pipeline(
    device: &wgpu::Device,
    layout: &wgpu::PipelineLayout,
    shader: &wgpu::ShaderModule,
    fragment: &str,
) -> wgpu::RenderPipeline {
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("Flat binding cache test"),
        layout: Some(layout),
        vertex: wgpu::VertexState {
            module: shader,
            entry_point: Some("vertex"),
            compilation_options: Default::default(),
            buffers: &[],
        },
        primitive: Default::default(),
        depth_stencil: None,
        multisample: Default::default(),
        fragment: Some(wgpu::FragmentState {
            module: shader,
            entry_point: Some(fragment),
            compilation_options: Default::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format: wgpu::TextureFormat::Rgba8Unorm,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview_mask: None,
        cache: None,
    })
}

#[test]
fn cached_bindings_reuse_resources_and_read_updated_indices() {
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
    let Ok(adapter) = pollster::block_on(instance.request_adapter(&Default::default())) else {
        eprintln!("no GPU adapter: skipped binding cache GPU test");
        return;
    };
    eprintln!("binding cache GPU: {:?}", adapter.get_info());
    let (device, queue) = pollster::block_on(adapter.request_device(&Default::default())).unwrap();
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: None,
        source: wgpu::ShaderSource::Wgsl(
            "
@vertex fn vertex(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
    return vec4<f32>(f32(i), 0.0, 0.0, 1.0);
}
@fragment fn fs_solid() -> @location(0) vec4<f32> { return vec4<f32>(1.0); }
@fragment fn fs_translucent() -> @location(0) vec4<f32> { return vec4<f32>(1.0); }
"
            .into(),
        ),
    });
    let globals = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: None,
        entries: &[],
    });
    let mut flat = Flat::new(&device, &globals, 256, |layout, _, fragment, _| {
        render_pipeline(&device, layout, &shader, fragment)
    });
    let mut uploads = super::super::upload::Uploads::new(&device);
    let mut encoder = device.create_command_encoder(&Default::default());
    let id = flat.add(&device, &mut encoder, &mut uploads, 0, 0, 4);
    uploads.finish(&encoder);
    queue.submit([encoder.finish()]);
    // COPY_SRC is only needed by this test's readback.
    flat.indices = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: 64,
        usage: wgpu::BufferUsages::INDEX
            | wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_DST
            | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    flat.index_capacity = 16;
    let storage = |data: &[u32]| {
        device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::cast_slice(data),
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        })
    };
    let sorted_a = storage(&[3, 2, 1, 0, 1, 2]);
    let sorted_b = storage(&[0, 2, 3, 1, 2, 3]);
    let phase_a = storage(&[6, 1, 0, 0, 0]);
    let phase_b = storage(&[6, 1, 0, 0, 0]);
    let mut draw = |flat: &mut Flat,
                    base: u32,
                    sorted: Option<&wgpu::Buffer>,
                    phase: Option<&wgpu::Buffer>| {
        let draws = [[6, 1, 0, base, 0]];
        let pages = [(0, sorted.map(|_| 0))];
        let solid = usize::from(sorted.is_none());
        let mut encoder = device.create_command_encoder(&Default::default());
        assert!(flat.prepare(
            &device,
            &mut encoder,
            &mut uploads,
            &draws,
            &pages,
            if phase.is_some() { 0 } else { solid },
            solid,
            [1; 2],
            phase,
            std::iter::once((id, [0.0; 4])),
            |_| sorted.unwrap().clone(),
        ));
        if phase.is_some() {
            flat.flatten_phase2(&mut encoder);
        }
        uploads.finish(&encoder);
        let read = device.create_buffer(&wgpu::BufferDescriptor {
            label: None,
            size: 24,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        encoder.copy_buffer_to_buffer(&flat.indices, 0, &read, 0, 24);
        queue.submit([encoder.finish()]);
        read.slice(..).map_async(wgpu::MapMode::Read, |_| {});
        device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
        let got: Vec<u32> =
            bytemuck::cast_slice(&read.slice(..).get_mapped_range().unwrap()).to_vec();
        let source = match sorted {
            Some(s) if *s == sorted_b => [0, 2, 3, 1, 2, 3],
            Some(_) => [3, 2, 1, 0, 1, 2],
            None => [0, 1, 2, 0, 2, 3],
        };
        assert_eq!(got, source.map(|i| base + i));
    };
    draw(&mut flat, 0, None, None);
    let first = flat.groups[0].group.clone();
    draw(&mut flat, 16, None, None);
    assert_eq!(flat.groups[0].group, first);
    draw(&mut flat, 16, Some(&sorted_a), None);
    let first_sorted = flat.groups[0].group.clone();
    assert_ne!(first_sorted, first);
    draw(&mut flat, 32, Some(&sorted_a), None);
    assert_eq!(flat.groups[0].group, first_sorted);
    draw(&mut flat, 32, Some(&sorted_b), None);
    assert_ne!(flat.groups[0].group, first_sorted);
    draw(&mut flat, 48, None, Some(&phase_a));
    assert!(flat.groups.is_empty());
    let first_phase = flat.phase2_group.as_ref().unwrap().group.clone();
    draw(&mut flat, 64, None, Some(&phase_a));
    assert_eq!(flat.phase2_group.as_ref().unwrap().group, first_phase);
    draw(&mut flat, 80, None, Some(&phase_b));
    assert_ne!(flat.phase2_group.as_ref().unwrap().group, first_phase);
    flat.idle();
    assert!(flat.groups.is_empty());
    assert!(flat.phase2_group.is_none());
    draw(&mut flat, 0, None, None);
    assert_eq!(flat.groups.len(), 1);
    flat.clear();
    assert!(flat.groups.is_empty());
    assert!(flat.phase2_group.is_none());
}
