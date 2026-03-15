import asyncio
import sys

import omni.kit.app
import omni.kit.asset_converter


def progress_callback(current_step: int, total_steps: int) -> None:
    print(f"[convert] {current_step}/{total_steps}")


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: convert_glb_to_usda.py <input> <output>")
        omni.kit.app.get_app().post_quit(-1)
        return

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    context = omni.kit.asset_converter.AssetConverterContext()
    context.ignore_materials = False
    context.ignore_animations = True
    context.ignore_camera = True
    context.ignore_light = True
    context.export_preview_surface = True
    context.use_meter_as_world_unit = False
    context.create_world_as_default_root_prim = False
    context.keep_all_materials = True
    context.merge_all_meshes = False
    context.disabling_instancing = True
    context.ignore_pivots = False

    converter = omni.kit.asset_converter.get_instance()
    task = converter.create_converter_task(
        input_path,
        output_path,
        progress_callback,
        context,
    )
    success = await task.wait_until_finished()

    print(f"[convert] success={success}")
    if not success:
        print(f"[convert] status={task.get_status()}")
        print(f"[convert] error={task.get_error_message()}")
        omni.kit.app.get_app().post_quit(-1)
        return

    omni.kit.app.get_app().post_quit(0)


asyncio.ensure_future(main())
