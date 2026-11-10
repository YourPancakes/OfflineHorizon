use super::{
    Globals, Vertex,
    particle_batch::{ATTRIBUTES, ParticleVertex},
};
use wgpu::util::DeviceExt;

fn vertex_images(vertices: [Vertex; 4], alternate: Option<[Vertex; 4]>) -> Option<Vec<Vec<u8>>> {
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
    let Ok(adapter) = pollster::block_on(instance.request_adapter(&Default::default())) else {
        eprintln!("no GPU adapter: skipped vertex pixel comparison");
        return None;
    };
    let (device, queue) = pollster::block_on(adapter.request_device(&Default::default())).unwrap();
    let source = super::entity_shader();
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: None,
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let full_attributes = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Uint32,3=>Unorm8x4,4=>Uint8x4,5=>Snorm8x4,6=>Float32x2];
    let pipeline = |compact| {
        device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: None,
            layout: None,
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some(if compact { "vs_particle" } else { "vs_entity" }),
                compilation_options: Default::default(),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: if compact {
                        std::mem::size_of::<ParticleVertex>()
                    } else {
                        std::mem::size_of::<Vertex>()
                    } as u64,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: if compact {
                        &ATTRIBUTES
                    } else {
                        &full_attributes
                    },
                })],
            },
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_entity"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        })
    };
    let mut pipelines = vec![pipeline(false), pipeline(true)];
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: None,
        size: wgpu::Extent3d {
            width: 16,
            height: 16,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    let pixels: Vec<u8> = (0..256u32)
        .flat_map(|i| [(i % 16 * 17) as u8, (i / 16 * 17) as u8, 200, 180])
        .collect();
    queue.write_texture(
        tex.as_image_copy(),
        &pixels,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(64),
            rows_per_image: Some(16),
        },
        wgpu::Extent3d {
            width: 16,
            height: 16,
            depth_or_array_layers: 1,
        },
    );
    let texture_view = tex.create_view(&Default::default());
    let sampler = device.create_sampler(&Default::default());
    let compact = vertices.each_ref().map(ParticleVertex::from);
    let mut buffers = vec![
        device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX,
        }),
        device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::cast_slice(&compact),
            usage: wgpu::BufferUsages::VERTEX,
        }),
    ];
    if let Some(vertices) = alternate {
        pipelines.push(pipeline(false));
        buffers.push(
            device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: None,
                contents: bytemuck::cast_slice(&vertices),
                usage: wgpu::BufferUsages::VERTEX,
            }),
        );
    }
    let indices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytemuck::cast_slice(&[0u32, 1, 2, 2, 3, 0]),
        usage: wgpu::BufferUsages::INDEX,
    });
    let mut globals: Globals = bytemuck::Zeroable::zeroed();
    globals.view_proj = glam::Mat4::IDENTITY.to_cols_array_2d();
    globals.fog = [100.0; 4];
    let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytemuck::bytes_of(&globals),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let mut images = Vec::new();
    for (pipeline, vertices) in pipelines.iter().zip(&buffers) {
        let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&texture_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&texture_view),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: wgpu::BindingResource::TextureView(&texture_view),
                },
                wgpu::BindGroupEntry {
                    binding: 6,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 7,
                    resource: wgpu::BindingResource::TextureView(&texture_view),
                },
            ],
        });
        let output = device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width: 64,
                height: 64,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let view = output.create_view(&Default::default());
        let read = device.create_buffer(&wgpu::BufferDescriptor {
            label: None,
            size: 64 * 64 * 4,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            pass.set_pipeline(pipeline);
            pass.set_bind_group(0, &group, &[]);
            pass.set_vertex_buffer(0, vertices.slice(..));
            pass.set_index_buffer(indices.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..6, 0, 0..1);
        }
        encoder.copy_texture_to_buffer(
            output.as_image_copy(),
            wgpu::TexelCopyBufferInfo {
                buffer: &read,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(256),
                    rows_per_image: Some(64),
                },
            },
            wgpu::Extent3d {
                width: 64,
                height: 64,
                depth_or_array_layers: 1,
            },
        );
        queue.submit([encoder.finish()]);
        read.slice(..).map_async(wgpu::MapMode::Read, |_| {});
        device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
        images.push(read.slice(..).get_mapped_range().unwrap().to_vec());
    }
    Some(images)
}

fn fixture_vertices() -> [Vertex; 4] {
    [
        ([-0.8, -0.7, 0.5], [0.0, 0.0]),
        ([0.7, -0.7, 0.5], [1.0, 0.0]),
        ([0.7, 0.8, 0.5], [1.0, 1.0]),
        ([-0.8, 0.8, 0.5], [0.0, 1.0]),
    ]
    .map(|(pos, uv)| Vertex {
        pos,
        uv,
        layer: 15,
        color: 0xbbeeddcc,
        light: 0x0000b0e0,
        normal: [0; 4],
        glint_uv: [0.0; 2],
    })
}

#[test]
fn compact_particles_match_full_vertex_pixels() {
    let Some(images) = vertex_images(fixture_vertices(), None) else {
        return;
    };
    assert!(
        images[0].iter().any(|&v| v != 0),
        "fixture must draw visible particles"
    );
    assert_eq!(images[0], images[1], "compact particle pixels differ");
}

#[test]
fn adaptive_16bit_position_probe_detects_silhouette_changes() {
    let mut vertices = fixture_vertices();
    for v in &mut vertices {
        if v.pos[0] < 0.0 {
            v.pos[0] = -0.453125 + 1.0 / 4096.0;
        }
    }
    // Section-local positions cross a half-pixel edge after the camera origin is added.
    // Keep this probe separate from the lossless particle format.
    let quantized = vertices.map(|mut v| {
        let local = [v.pos[0] + 16.90625, v.pos[1], v.pos[2]];
        let largest = local.iter().map(|v| v.abs()).fold(0.0f32, f32::max);
        let mut exponent = largest.log2().floor() as i32 - 14;
        let mut scale = 2.0f32.powi(-exponent);
        if (largest * scale).round() > f32::from(i16::MAX) {
            exponent += 1;
            scale *= 0.5;
        }
        let decoded = local.map(|p| f32::from((p * scale).round() as i16) * 2.0f32.powi(exponent));
        v.pos = [decoded[0] - 16.90625, decoded[1], decoded[2]];
        v
    });
    let Some(images) = vertex_images(vertices, Some(quantized)) else {
        return;
    };
    let changed = images[0]
        .as_chunks::<4>()
        .0
        .iter()
        .zip(images[2].as_chunks::<4>().0)
        .filter(|(a, b)| a != b)
        .count();
    eprintln!("adaptive 16-bit position probe: changed_pixels={changed}/4096");
    assert!(
        changed > 0,
        "the probe must expose the proposed quantization's precision loss"
    );
}
