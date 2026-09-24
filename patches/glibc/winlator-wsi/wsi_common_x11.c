/*
 * Copyright © 2015 Intel Corporation
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice (including the next
 * paragraph) shall be included in all copies or substantial portions of the
 * Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
 * IN THE SOFTWARE.
 */

#include <X11/Xlib-xcb.h>
#include <xcb/xcb.h>
#include <xcb/dri3.h>
#include <xcb/present.h>
#include <xcb/shm.h>

#include "util/macros.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include "util/hash_table.h"
#include "util/os_file.h"
#include "util/os_time.h"
#include "util/u_debug.h"
#include "util/u_thread.h"
#include "util/timespec.h"

#include "vk_format.h"
#include "vk_instance.h"
#include "vk_physical_device.h"
#include "vk_util.h"
#include "vk_enum_to_str.h"
#include "wsi_common_entrypoints.h"
#include "wsi_common_private.h"
#include "wsi_common_queue.h"

#ifdef HAVE_SYS_SHM_H
#include <sys/ipc.h>
#include <sys/shm.h>
#endif

struct wsi_x11_connection {
   bool has_dri3;
   bool has_present;
   bool has_mit_shm;
};

struct wsi_x11 {
   struct wsi_interface base;
   pthread_mutex_t mutex;
   struct hash_table *connections;
};

struct wsi_x11_image {
   struct wsi_image base;
   xcb_pixmap_t pixmap;
   atomic_bool busy;
   xcb_shm_seg_t shmseg;
   int shmid;
   uint8_t *shmaddr;
   uint64_t present_id;
};

struct wsi_x11_swapchain {
   struct wsi_swapchain base;
   bool has_mit_shm;

   xcb_connection_t *conn;
   xcb_window_t window;
   xcb_gc_t gc;
   uint32_t depth;
   VkExtent2D extent;

   bool has_present_queue;
   VkResult status;
   struct wsi_queue present_queue;
   pthread_t queue_thread;

   pthread_mutex_t image_pool_mutex;
   pthread_cond_t image_pool_cond;

   pthread_mutex_t present_id_mutex;
   pthread_cond_t present_id_cond; 

   uint64_t present_id;

   struct wsi_x11_image images[0];
};

static struct wsi_x11_connection *
wsi_x11_connection_create(struct wsi_device *wsi_dev,
                          xcb_connection_t *conn)
{
   xcb_query_extension_cookie_t dri3_cookie, pres_cookie, shm_cookie;
   xcb_query_extension_reply_t *dri3_reply, *pres_reply, *shm_reply = NULL;
   bool wants_shm = wsi_dev->sw && !(WSI_DEBUG & WSI_DEBUG_NOSHM);

   struct wsi_x11_connection *wsi_conn =
      vk_alloc(&wsi_dev->instance_alloc, sizeof(*wsi_conn), 8,
                VK_SYSTEM_ALLOCATION_SCOPE_INSTANCE);
   if (!wsi_conn)
      return NULL;

   dri3_cookie = xcb_query_extension(conn, 4, "DRI3");
   pres_cookie = xcb_query_extension(conn, 7, "Present");

   dri3_reply = xcb_query_extension_reply(conn, dri3_cookie, NULL);
   pres_reply = xcb_query_extension_reply(conn, pres_cookie, NULL);

   if (!dri3_reply || !pres_reply) {
      free(dri3_reply);
      free(pres_reply);
      vk_free(&wsi_dev->instance_alloc, wsi_conn);
      return NULL;
   }

   wsi_conn->has_dri3 = dri3_reply->present != 0;
   wsi_conn->has_present = pres_reply->present != 0;

   free(dri3_reply);
   free(pres_reply);

   wsi_conn->has_mit_shm = false;
   if (wants_shm) {
      shm_cookie = xcb_query_extension(conn, 7, "MIT-SHM");
	  xcb_query_extension_reply_t *shm_reply = xcb_query_extension_reply(conn, shm_cookie, NULL);
	  wsi_conn->has_mit_shm = shm_reply->present != 0;
	  free(shm_reply);
   }

   return wsi_conn;
}

static void
wsi_x11_connection_destroy(struct wsi_device *wsi_dev,
                           struct wsi_x11_connection *conn)
{
   vk_free(&wsi_dev->instance_alloc, conn);
}

static struct wsi_x11_connection *
wsi_x11_get_connection(struct wsi_device *wsi_dev,
                       xcb_connection_t *conn)
{
   struct wsi_x11 *wsi =
      (struct wsi_x11 *)wsi_dev->wsi[VK_ICD_WSI_PLATFORM_XCB];

   pthread_mutex_lock(&wsi->mutex);

   struct hash_entry *entry = _mesa_hash_table_search(wsi->connections, conn);
   if (!entry) {
      pthread_mutex_unlock(&wsi->mutex);

      struct wsi_x11_connection *wsi_conn =
         wsi_x11_connection_create(wsi_dev, conn);
      if (!wsi_conn)
         return NULL;

      pthread_mutex_lock(&wsi->mutex);

      entry = _mesa_hash_table_search(wsi->connections, conn);
      if (entry) {
         wsi_x11_connection_destroy(wsi_dev, wsi_conn);
      } else {
         entry = _mesa_hash_table_insert(wsi->connections, conn, wsi_conn);
      }
   }

   pthread_mutex_unlock(&wsi->mutex);

   return entry->data;
}

static const VkFormat formats[] = {
   VK_FORMAT_R5G6B5_UNORM_PACK16,
   VK_FORMAT_B8G8R8A8_SRGB,
   VK_FORMAT_B8G8R8A8_UNORM,
   VK_FORMAT_A2R10G10B10_UNORM_PACK32,
};

static const VkPresentModeKHR present_modes[] = {
   VK_PRESENT_MODE_IMMEDIATE_KHR,
   VK_PRESENT_MODE_MAILBOX_KHR,
   VK_PRESENT_MODE_FIFO_KHR,
   VK_PRESENT_MODE_FIFO_RELAXED_KHR,
};

static xcb_screen_t *
get_screen_for_root(xcb_connection_t *conn, xcb_window_t root)
{
   xcb_screen_iterator_t screen_iter =
      xcb_setup_roots_iterator(xcb_get_setup(conn));

   for (; screen_iter.rem; xcb_screen_next (&screen_iter)) {
      if (screen_iter.data->root == root)
         return screen_iter.data;
   }

   return NULL;
}

static xcb_visualtype_t *
screen_get_visualtype(xcb_screen_t *screen, xcb_visualid_t visual_id,
                      unsigned *depth)
{
   xcb_depth_iterator_t depth_iter =
      xcb_screen_allowed_depths_iterator(screen);

   for (; depth_iter.rem; xcb_depth_next (&depth_iter)) {
      xcb_visualtype_iterator_t visual_iter =
         xcb_depth_visuals_iterator (depth_iter.data);

      for (; visual_iter.rem; xcb_visualtype_next (&visual_iter)) {
         if (visual_iter.data->visual_id == visual_id) {
            if (depth)
               *depth = depth_iter.data->depth;
            return visual_iter.data;
         }
      }
   }

   return NULL;
}

static xcb_visualtype_t *
connection_get_visualtype(xcb_connection_t *conn, xcb_visualid_t visual_id)
{
   xcb_screen_iterator_t screen_iter = 
      xcb_setup_roots_iterator(xcb_get_setup(conn));

   for (; screen_iter.rem; xcb_screen_next (&screen_iter)) {
      xcb_visualtype_t *visual = screen_get_visualtype(screen_iter.data,
                                                       visual_id, NULL);
      if (visual)
         return visual;
   }

   return NULL;
}

static xcb_visualtype_t *
get_visualtype_for_window(xcb_connection_t *conn, xcb_window_t window,
                          unsigned *depth, xcb_visualtype_t **rootvis)
{
   xcb_query_tree_cookie_t tree_cookie;
   xcb_get_window_attributes_cookie_t attrib_cookie;
   xcb_query_tree_reply_t *tree;
   xcb_get_window_attributes_reply_t *attrib;

   tree_cookie = xcb_query_tree(conn, window);
   attrib_cookie = xcb_get_window_attributes(conn, window);

   tree = xcb_query_tree_reply(conn, tree_cookie, NULL);
   attrib = xcb_get_window_attributes_reply(conn, attrib_cookie, NULL);
   if (attrib == NULL || tree == NULL) {
      free(attrib);
      free(tree);
      return NULL;
   }

   xcb_window_t root = tree->root;
   xcb_visualid_t visual_id = attrib->visual;
   free(attrib);
   free(tree);

   xcb_screen_t *screen = get_screen_for_root(conn, root);
   if (screen == NULL)
      return NULL;

   if (rootvis)
      *rootvis = screen_get_visualtype(screen, screen->root_visual, depth);
   return screen_get_visualtype(screen, visual_id, depth);
}

static bool
visual_has_alpha(xcb_visualtype_t *visual, unsigned depth)
{
   uint32_t rgb_mask = visual->red_mask |
                       visual->green_mask |
                       visual->blue_mask;

   uint32_t all_mask = 0xffffffff >> (32 - depth);
   return (all_mask & ~rgb_mask) != 0;
}

static bool
visual_supported(xcb_visualtype_t *visual)
{
   if (!visual)
      return false;

   return visual->_class == XCB_VISUAL_CLASS_TRUE_COLOR ||
          visual->_class == XCB_VISUAL_CLASS_DIRECT_COLOR;
}

VKAPI_ATTR VkBool32 VKAPI_CALL
wsi_GetPhysicalDeviceXcbPresentationSupportKHR(VkPhysicalDevice physicalDevice,
                                               uint32_t queueFamilyIndex,
                                               xcb_connection_t *connection,
                                               xcb_visualid_t visual_id)
{
   VK_FROM_HANDLE(vk_physical_device, pdevice, physicalDevice);
   struct wsi_device *wsi_device = pdevice->wsi_device;
   struct wsi_x11_connection *wsi_conn =
      wsi_x11_get_connection(wsi_device, connection);

   if (!wsi_conn)
      return false;

   if (!wsi_device->sw && !wsi_conn->has_dri3)
      return false;

   if (!visual_supported(connection_get_visualtype(connection, visual_id)))
      return false;

   return true;
}

VKAPI_ATTR VkBool32 VKAPI_CALL
wsi_GetPhysicalDeviceXlibPresentationSupportKHR(VkPhysicalDevice physicalDevice,
                                                uint32_t queueFamilyIndex,
                                                Display *dpy,
                                                VisualID visualID)
{
   return wsi_GetPhysicalDeviceXcbPresentationSupportKHR(physicalDevice,
                                                         queueFamilyIndex,
                                                         XGetXCBConnection(dpy),
                                                         visualID);
}

static xcb_connection_t*
wsi_x11_surface_get_connection(VkIcdSurfaceBase *icd_surface)
{
   if (icd_surface->platform == VK_ICD_WSI_PLATFORM_XLIB)
      return XGetXCBConnection(((VkIcdSurfaceXlib *)icd_surface)->dpy);
   else
      return ((VkIcdSurfaceXcb *)icd_surface)->connection;
}

static xcb_window_t
wsi_x11_surface_get_window(VkIcdSurfaceBase *icd_surface)
{
   if (icd_surface->platform == VK_ICD_WSI_PLATFORM_XLIB)
      return ((VkIcdSurfaceXlib *)icd_surface)->window;
   else
      return ((VkIcdSurfaceXcb *)icd_surface)->window;
}

static VkResult
wsi_x11_surface_get_support(VkIcdSurfaceBase *icd_surface,
                            struct wsi_device *wsi_device,
                            uint32_t queueFamilyIndex,
                            VkBool32* pSupported)
{
   xcb_connection_t *conn = wsi_x11_surface_get_connection(icd_surface);
   xcb_window_t window = wsi_x11_surface_get_window(icd_surface);

   struct wsi_x11_connection *wsi_conn =
      wsi_x11_get_connection(wsi_device, conn);
   if (!wsi_conn)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   if (!wsi_device->sw && !wsi_conn->has_dri3) {
      *pSupported = false;
      return VK_SUCCESS;
   }

   if (!visual_supported(get_visualtype_for_window(conn, window, NULL, NULL))) {
      *pSupported = false;
      return VK_SUCCESS;
   }

   *pSupported = true;
   return VK_SUCCESS;
}

/* Winlator: present through the window's hardware buffer, shared by the X
 * server over DRI3 BufferFromPixmap. Winlator up to app version 32 sets
 * MESA_VK_WSI_USE_HWBUF, later versions set MESA_VK_WSI_NATIVE_MEM_IMPORTED.
 */
static bool
wsi_x11_env_enabled(const char *name)
{
   const char *value = getenv(name);
   return value && (!strcmp(value, "true") || !strcmp(value, "1"));
}

static bool
wsi_x11_use_hwbuf(void)
{
   return wsi_x11_env_enabled("MESA_VK_WSI_USE_HWBUF") ||
          wsi_x11_env_enabled("MESA_VK_WSI_NATIVE_MEM_IMPORTED");
}

static uint32_t
wsi_x11_get_min_image_count(const struct wsi_device *wsi_device, const VkSurfacePresentModeEXT *present_mode)
{
   if (wsi_device->sw || wsi_x11_use_hwbuf())
      return 1;
   else if (present_mode && 
            present_mode->presentMode == VK_PRESENT_MODE_MAILBOX_KHR)
      return 4;
   else
      return 2;
}

static VkResult
wsi_x11_surface_get_capabilities(VkIcdSurfaceBase *icd_surface,
                                 struct wsi_device *wsi_device,
                                 const VkSurfacePresentModeEXT *present_mode,
                                 VkSurfaceCapabilitiesKHR *caps)
{
   xcb_connection_t *conn = wsi_x11_surface_get_connection(icd_surface);
   xcb_window_t window = wsi_x11_surface_get_window(icd_surface);
   struct wsi_x11_connection *wsi_conn =
      wsi_x11_get_connection(wsi_device, conn);
   xcb_get_geometry_cookie_t geom_cookie;
   xcb_generic_error_t *err;
   xcb_get_geometry_reply_t *geom;
   unsigned visual_depth;

   geom_cookie = xcb_get_geometry(conn, window);

   xcb_visualtype_t *visual =
      get_visualtype_for_window(conn, window, &visual_depth, NULL);

   if (!visual)
      return VK_ERROR_SURFACE_LOST_KHR;

   geom = xcb_get_geometry_reply(conn, geom_cookie, &err);
   if (geom) {
      VkExtent2D extent = { geom->width, geom->height };
      caps->currentExtent = extent;
      caps->minImageExtent = extent;
      caps->maxImageExtent = extent;
   }
   free(err);
   free(geom);
   if (!geom)
       return VK_ERROR_SURFACE_LOST_KHR;

   if (visual_has_alpha(visual, visual_depth)) {
      caps->supportedCompositeAlpha = VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR |
                                      VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
   } else {
      caps->supportedCompositeAlpha = VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR |
                                      VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
   }

   caps->minImageCount = wsi_x11_get_min_image_count(wsi_device, present_mode);
   caps->maxImageCount = caps->minImageCount == 1 ? 2 : 0;

   caps->supportedTransforms = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
   caps->currentTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
   caps->maxImageArrayLayers = 1;
   caps->supportedUsageFlags =
      VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
      VK_IMAGE_USAGE_SAMPLED_BIT |
      VK_IMAGE_USAGE_TRANSFER_DST_BIT |
      VK_IMAGE_USAGE_STORAGE_BIT |
      VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
      VK_IMAGE_USAGE_INPUT_ATTACHMENT_BIT;

   return VK_SUCCESS;
}

static VkResult
wsi_x11_surface_get_capabilities2(VkIcdSurfaceBase *icd_surface,
                                  struct wsi_device *wsi_device,
                                  const void *info_next,
                                  VkSurfaceCapabilities2KHR *caps)
{
   assert(caps->sType == VK_STRUCTURE_TYPE_SURFACE_CAPABILITIES_2_KHR);

   const VkSurfacePresentModeEXT *present_mode = vk_find_struct_const(info_next, SURFACE_PRESENT_MODE_EXT);

   VkResult result =
      wsi_x11_surface_get_capabilities(icd_surface, wsi_device, present_mode,
                                       &caps->surfaceCapabilities);

   if (result != VK_SUCCESS)
      return result;

   vk_foreach_struct(stype, ext, caps->pNext) {
      switch (stype) {
      case VK_STRUCTURE_TYPE_SURFACE_PROTECTED_CAPABILITIES_KHR: {
         VkSurfaceProtectedCapabilitiesKHR *protected = (void *)ext;
         protected->supportsProtected = VK_FALSE;
         break;
      }

      case VK_STRUCTURE_TYPE_SURFACE_PRESENT_SCALING_CAPABILITIES_EXT: {
         /* Unsupported. */
         VkSurfacePresentScalingCapabilitiesEXT *scaling = (void *)ext;
         scaling->supportedPresentScaling = 0;
         scaling->supportedPresentGravityX = 0;
         scaling->supportedPresentGravityY = 0;
         scaling->minScaledImageExtent = caps->surfaceCapabilities.minImageExtent;
         scaling->maxScaledImageExtent = caps->surfaceCapabilities.maxImageExtent;
         break;
      }

      case VK_STRUCTURE_TYPE_SURFACE_PRESENT_MODE_COMPATIBILITY_EXT: {
         VkSurfacePresentModeCompatibilityEXT *compat = (void *)ext;
         if (compat->pPresentModes) {
            if (compat->presentModeCount) {
               assert(present_mode);
               compat->pPresentModes[0] = present_mode->presentMode;
               compat->presentModeCount = 1;
            }
         } else {
            compat->presentModeCount = 1;
         }
         break;
      }

      default:
         break;
      }
   }

   return result;
}

static int
format_get_component_bits(VkFormat format, int comp)
{
   return vk_format_get_component_bits(format, UTIL_FORMAT_COLORSPACE_RGB, comp);
}

static bool
rgb_component_bits_are_equal(VkFormat format, const xcb_visualtype_t* type)
{
   return format_get_component_bits(format, 0) == util_bitcount(type->red_mask) &&
          format_get_component_bits(format, 1) == util_bitcount(type->green_mask) &&
          format_get_component_bits(format, 2) == util_bitcount(type->blue_mask);
}

static bool
get_sorted_vk_formats(VkIcdSurfaceBase *surface, struct wsi_device *wsi_device,
                      VkFormat *sorted_formats, unsigned *count)
{
   xcb_connection_t *conn = wsi_x11_surface_get_connection(surface);
   xcb_window_t window = wsi_x11_surface_get_window(surface);
   xcb_visualtype_t *rootvis = NULL;
   xcb_visualtype_t *visual = get_visualtype_for_window(conn, window, NULL, &rootvis);

   if (!visual)
      return false;

   /* use the root window's visual to set the default */
   *count = 0;
   for (unsigned i = 0; i < ARRAY_SIZE(formats); i++) {
      if (rgb_component_bits_are_equal(formats[i], rootvis))
         sorted_formats[(*count)++] = formats[i];
   }

   for (unsigned i = 0; i < ARRAY_SIZE(formats); i++) {
      for (unsigned j = 0; j < *count; j++)
         if (formats[i] == sorted_formats[j])
            goto next_format;
      if (rgb_component_bits_are_equal(formats[i], visual))
         sorted_formats[(*count)++] = formats[i];
next_format:;
   }

   if (wsi_device->force_bgra8_unorm_first) {
      for (unsigned i = 0; i < *count; i++) {
         if (sorted_formats[i] == VK_FORMAT_B8G8R8A8_UNORM) {
            sorted_formats[i] = sorted_formats[0];
            sorted_formats[0] = VK_FORMAT_B8G8R8A8_UNORM;
            break;
         }
      }
   }

   return true;
}

static VkResult
wsi_x11_surface_get_formats(VkIcdSurfaceBase *surface,
                            struct wsi_device *wsi_device,
                            uint32_t *pSurfaceFormatCount,
                            VkSurfaceFormatKHR *pSurfaceFormats)
{
   VK_OUTARRAY_MAKE_TYPED(VkSurfaceFormatKHR, out,
                          pSurfaceFormats, pSurfaceFormatCount);

   unsigned count;
   VkFormat sorted_formats[ARRAY_SIZE(formats)];
   if (!get_sorted_vk_formats(surface, wsi_device, sorted_formats, &count))
      return VK_ERROR_SURFACE_LOST_KHR;

   for (unsigned i = 0; i < count; i++) {
      vk_outarray_append_typed(VkSurfaceFormatKHR, &out, f) {
         f->format = sorted_formats[i];
         f->colorSpace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
      }
   }

   return vk_outarray_status(&out);
}

static VkResult
wsi_x11_surface_get_formats2(VkIcdSurfaceBase *surface,
                             struct wsi_device *wsi_device,
                             const void *info_next,
                             uint32_t *pSurfaceFormatCount,
                             VkSurfaceFormat2KHR *pSurfaceFormats)
{
   VK_OUTARRAY_MAKE_TYPED(VkSurfaceFormat2KHR, out,
                          pSurfaceFormats, pSurfaceFormatCount);

   unsigned count;
   VkFormat sorted_formats[ARRAY_SIZE(formats)];
   if (!get_sorted_vk_formats(surface, wsi_device, sorted_formats, &count))
      return VK_ERROR_SURFACE_LOST_KHR;

   for (unsigned i = 0; i < count; i++) {
      vk_outarray_append_typed(VkSurfaceFormat2KHR, &out, f) {
         assert(f->sType == VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR);
         f->surfaceFormat.format = sorted_formats[i];
         f->surfaceFormat.colorSpace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
      }
   }

   return vk_outarray_status(&out);
}

static VkResult
wsi_x11_surface_get_present_modes(VkIcdSurfaceBase *surface,
                                  struct wsi_device *wsi_device,
                                  uint32_t *pPresentModeCount,
                                  VkPresentModeKHR *pPresentModes)
{
   if (pPresentModes == NULL) {
      *pPresentModeCount = ARRAY_SIZE(present_modes);
      return VK_SUCCESS;
   }

   *pPresentModeCount = MIN2(*pPresentModeCount, ARRAY_SIZE(present_modes));
   typed_memcpy(pPresentModes, present_modes, *pPresentModeCount);

   return *pPresentModeCount < ARRAY_SIZE(present_modes) ?
      VK_INCOMPLETE : VK_SUCCESS;
}

static VkResult
wsi_x11_surface_get_present_rectangles(VkIcdSurfaceBase *icd_surface,
                                       struct wsi_device *wsi_device,
                                       uint32_t* pRectCount,
                                       VkRect2D* pRects)
{
   xcb_connection_t *conn = wsi_x11_surface_get_connection(icd_surface);
   xcb_window_t window = wsi_x11_surface_get_window(icd_surface);
   VK_OUTARRAY_MAKE_TYPED(VkRect2D, out, pRects, pRectCount);

   vk_outarray_append_typed(VkRect2D, &out, rect) {
      xcb_generic_error_t *err = NULL;
      xcb_get_geometry_cookie_t geom_cookie = xcb_get_geometry(conn, window);
      xcb_get_geometry_reply_t *geom =
         xcb_get_geometry_reply(conn, geom_cookie, &err);
      free(err);
      if (geom) {
         *rect = (VkRect2D) {
            .offset = { 0, 0 },
            .extent = { geom->width, geom->height },
         };
      }
      free(geom);
      if (!geom)
          return VK_ERROR_SURFACE_LOST_KHR;
   }

   return vk_outarray_status(&out);
}

VKAPI_ATTR VkResult VKAPI_CALL
wsi_CreateXcbSurfaceKHR(VkInstance _instance,
                        const VkXcbSurfaceCreateInfoKHR *pCreateInfo,
                        const VkAllocationCallbacks *pAllocator,
                        VkSurfaceKHR *pSurface)
{
   VK_FROM_HANDLE(vk_instance, instance, _instance);
   VkIcdSurfaceXcb *surface;

   assert(pCreateInfo->sType == VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR);

   surface = vk_alloc2(&instance->alloc, pAllocator, sizeof *surface, 8,
                       VK_SYSTEM_ALLOCATION_SCOPE_OBJECT);
   if (surface == NULL)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   surface->base.platform = VK_ICD_WSI_PLATFORM_XCB;
   surface->connection = pCreateInfo->connection;
   surface->window = pCreateInfo->window;

   *pSurface = VkIcdSurfaceBase_to_handle(&surface->base);
   return VK_SUCCESS;
}

VKAPI_ATTR VkResult VKAPI_CALL
wsi_CreateXlibSurfaceKHR(VkInstance _instance,
                         const VkXlibSurfaceCreateInfoKHR *pCreateInfo,
                         const VkAllocationCallbacks *pAllocator,
                         VkSurfaceKHR *pSurface)
{
   VK_FROM_HANDLE(vk_instance, instance, _instance);
   VkIcdSurfaceXlib *surface;

   assert(pCreateInfo->sType == VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR);

   surface = vk_alloc2(&instance->alloc, pAllocator, sizeof *surface, 8,
                       VK_SYSTEM_ALLOCATION_SCOPE_OBJECT);
   if (surface == NULL)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   surface->base.platform = VK_ICD_WSI_PLATFORM_XLIB;
   surface->dpy = pCreateInfo->dpy;
   surface->window = pCreateInfo->window;

   *pSurface = VkIcdSurfaceBase_to_handle(&surface->base);
   return VK_SUCCESS;
}

VK_DEFINE_NONDISP_HANDLE_CASTS(wsi_x11_swapchain, base.base, VkSwapchainKHR,
                               VK_OBJECT_TYPE_SWAPCHAIN_KHR)

static void
wsi_x11_notify_idle_image(struct wsi_x11_swapchain *chain, struct wsi_x11_image *image)
{
   pthread_mutex_lock(&chain->image_pool_mutex);

   if (image) 
      image->busy = false;
  
   pthread_cond_broadcast(&chain->image_pool_cond);
   pthread_mutex_unlock(&chain->image_pool_mutex);
}

static void 
wsi_x11_notify_present_success(struct wsi_x11_swapchain *chain, struct wsi_x11_image *image)
{
   if (image->present_id) {
      pthread_mutex_lock(&chain->present_id_mutex);

      if (image->present_id > chain->present_id)
         chain->present_id = image->present_id;

      pthread_cond_broadcast(&chain->present_id_cond);
      pthread_mutex_unlock(&chain->present_id_mutex);
   }
}

static void 
wsi_x11_notify_present_error(struct wsi_x11_swapchain *chain)
{
   pthread_mutex_lock(&chain->present_id_mutex);
   chain->present_id = UINT64_MAX;
   pthread_cond_broadcast(&chain->present_id_cond);
   pthread_mutex_unlock(&chain->present_id_mutex);
}

static VkResult
wsi_x11_swapchain_result(struct wsi_x11_swapchain *chain, VkResult result)
{
   if (result < 0)
      wsi_x11_notify_present_error(chain);

   if (chain->status < 0)
      return chain->status;

   if (result < 0) {
      chain->status = result;
      return result;
   }

   if (result == VK_TIMEOUT || result == VK_NOT_READY)
      return result;

   if (result == VK_SUBOPTIMAL_KHR) {
      chain->status = result;
      return result;
   }

   return chain->status;
}

static struct wsi_image *
wsi_x11_get_wsi_image(struct wsi_swapchain *wsi_chain, uint32_t image_index)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)wsi_chain;
   return &chain->images[image_index].base;
}

static VkResult
wsi_x11_present_image_dri3(struct wsi_x11_swapchain *chain, uint32_t image_index)
{
   struct wsi_x11_image *image = &chain->images[image_index];

   assert(image_index < chain->base.image_count);

   struct wsi_x11_connection *wsi_conn =
      wsi_x11_get_connection((struct wsi_device*)chain->base.wsi, chain->conn);
   if (!wsi_conn)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   xcb_void_cookie_t cookie =
      xcb_present_pixmap(chain->conn,
                         chain->window,
                         image->pixmap,
                         0,             /* serial */
                         XCB_NONE,      /* valid */
                         XCB_NONE,      /* update */
                         0,             /* x_off */
                         0,             /* y_off */
                         XCB_NONE,      /* target_crtc */
                         XCB_NONE,      /* wait_fence */
                         XCB_NONE,      /* idle_fence */
                         XCB_PRESENT_OPTION_NONE,
                         0,             /* target_msc */
                         0,             /* divisor */ 
                         0,             /* remainder */ 
                         0,             /* notifies_len */
                         NULL);

   xcb_discard_reply(chain->conn, cookie.sequence);
   xcb_flush(chain->conn);
   return wsi_x11_swapchain_result(chain, VK_SUCCESS);
}

static VkResult
wsi_x11_present_image_sw(struct wsi_x11_swapchain *chain, uint32_t image_index)
{
   struct wsi_x11_image *image = &chain->images[image_index];
   xcb_void_cookie_t cookie;

   if (chain->has_mit_shm) {
      memcpy(image->shmaddr, image->base.cpu_map, image->base.row_pitches[0] * chain->extent.height);
      cookie = xcb_shm_put_image(chain->conn,
                                 chain->window,
								 chain->gc,
								 image->base.row_pitches[0] / 4,
								 chain->extent.height,
								 0, 0,
								 chain->extent.width,
								 chain->extent.height,
								 0, 0, chain->depth, XCB_IMAGE_FORMAT_Z_PIXMAP, 
								 0,
								 image->shmseg,
								 0);
      xcb_discard_reply(chain->conn, cookie.sequence);
   }
   else {
      cookie = xcb_put_image(chain->conn, XCB_IMAGE_FORMAT_Z_PIXMAP,
                             chain->window,
                             chain->gc,
                             image->base.row_pitches[0] / 4,
                             chain->extent.height,
                             0, 0, 0, chain->depth,
                             image->base.row_pitches[0] * chain->extent.height,
                             image->base.cpu_map);
      xcb_discard_reply(chain->conn, cookie.sequence);
   }

   xcb_flush(chain->conn);
   image->busy = false;
   return VK_SUCCESS;  
}

static VkResult
wsi_x11_present_image(struct wsi_x11_swapchain *chain, uint32_t image_index)
{
   VkResult result;
   if (chain->base.wsi->sw)
      result = wsi_x11_present_image_sw(chain, image_index);
   else
      result = wsi_x11_present_image_dri3(chain, image_index);

   if (result < 0)
      wsi_x11_notify_present_error(chain);
   else
      wsi_x11_notify_present_success(chain, &chain->images[image_index]);

   return result;
}

static VkResult
wsi_x11_release_images(struct wsi_swapchain *wsi_chain,
                       uint32_t count, const uint32_t *indices)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)wsi_chain;
   if (chain->status == VK_ERROR_SURFACE_LOST_KHR)
      return chain->status;

   for (uint32_t i = 0; i < count; i++) {
      uint32_t index = indices[i];
      chain->images[index].busy = false;
   }

   return VK_SUCCESS;
}

static VkResult
wsi_x11_acquire_next_image(struct wsi_swapchain *wsi_chain,
                           const VkAcquireNextImageInfoKHR *info,
                           uint32_t *image_index)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)wsi_chain;
   xcb_generic_event_t *event;
   VkResult result;
   struct timespec abs_timespec;
   uint64_t abs_timeout = 0;

   /* If the swapchain is broken, don't go any further. */
   if (chain->status < 0)
      return chain->status;
  
   if (info->timeout != UINT64_MAX) {
      if (info->timeout != 0)
         abs_timeout = os_time_get_absolute_timeout(info->timeout);

      timespec_from_nsec(&abs_timespec, abs_timeout);
   }

   while (chain->status >= 0) {
      for (uint32_t i = 0; i < chain->base.image_count; i++) {
         if (!chain->images[i].busy) {
            *image_index = i;
            chain->images[i].busy = true;
            return VK_SUCCESS;
         }
      }

      if (chain->base.wsi->sw)
         return VK_NOT_READY;

      pthread_mutex_lock(&chain->image_pool_mutex);

      int ret;
      if (info->timeout == UINT64_MAX)
         ret = pthread_cond_wait(&chain->image_pool_cond,
                                 &chain->image_pool_mutex);
      else
         ret = pthread_cond_timedwait(&chain->image_pool_cond,
                                      &chain->image_pool_mutex,
                                      &abs_timespec);
      if (ret == ETIMEDOUT)
         result = VK_TIMEOUT;
      else if (ret)
         result = VK_ERROR_DEVICE_LOST;

      pthread_mutex_unlock(&chain->image_pool_mutex);

      if (result < 0)
          break;
   }

   if (chain->status < 0)
      return chain->status;

   return result;
}

static VkResult
wsi_x11_queue_present(struct wsi_swapchain *anv_chain,
                      uint32_t image_index,
                      uint64_t present_id,
                      const VkPresentRegionKHR *damage)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)anv_chain;
   VkResult result;

   /* If the swapchain is broken, don't go any further. */
   if (chain->status < 0)
      return chain->status;

   chain->images[image_index].present_id = present_id;
   chain->images[image_index].busy = true;

   if (chain->has_present_queue) {
      wsi_queue_push(&chain->present_queue, image_index);
      result = chain->status;
   } else {
      result = wsi_x11_present_image(chain, image_index);
      chain->images[image_index].busy = false;
   }

   return result;
}

static void *
wsi_x11_present_queue_thread(void *state)
{
   struct wsi_x11_swapchain *chain = state;
   uint32_t image_index = 0;
   VkResult result = VK_SUCCESS;

   while (chain->status >= 0) {
      image_index = 0;
      result = wsi_queue_pull(&chain->present_queue, &image_index, INT64_MAX);

      if (result < 0 || chain->status < 0)
         break;

      if (chain->base.image_info.hwbuf_fd <= 0) {
         result = chain->base.wsi->WaitForFences(chain->base.device, 1,
                                                 &chain->base.fences[image_index],
                                                 true, UINT64_MAX);
         if (result != VK_SUCCESS) {
            result = VK_ERROR_OUT_OF_DATE_KHR;
            break;
         }
      }

      result = wsi_x11_present_image(chain, image_index);
      if (result < 0)
         break;

      wsi_x11_notify_idle_image(chain, &chain->images[image_index]);
   }

   wsi_x11_swapchain_result(chain, result);
   wsi_x11_notify_idle_image(chain, NULL);
   return NULL;
}

static uint8_t *
alloc_shm(struct wsi_image *imagew, unsigned size)
{
#ifdef HAVE_SYS_SHM_H
   struct wsi_x11_image *image = (struct wsi_x11_image *)imagew;
   image->shmid = shmget(IPC_PRIVATE, size, IPC_CREAT | 0600);
   if (image->shmid < 0)
      return NULL;

   uint8_t *addr = (uint8_t *)shmat(image->shmid, 0, 0);
   /* mark the segment immediately for deletion to avoid leaks */
   shmctl(image->shmid, IPC_RMID, 0);

   if (addr == (uint8_t *) -1)
      return NULL;

   image->shmaddr = addr;
   return addr;
#else
   return NULL;
#endif
}

static VkResult
wsi_x11_image_init(VkDevice device_h, struct wsi_x11_swapchain *chain,
                   const VkSwapchainCreateInfoKHR *pCreateInfo,
                   const VkAllocationCallbacks* pAllocator,
                   struct wsi_x11_image *image)
{
   xcb_void_cookie_t cookie;
   VkResult result;
   uint32_t bpp = 32;

   result = wsi_create_image(&chain->base, &chain->base.image_info,
                             &image->base);
   if (result != VK_SUCCESS)
      return result;

   if (chain->base.wsi->sw) {
      if (!chain->has_mit_shm) {
         image->busy = false;
         return VK_SUCCESS;
      }
	  
      alloc_shm(&image->base, image->base.row_pitches[0] * chain->extent.height);	  

      image->shmseg = xcb_generate_id(chain->conn);

      xcb_shm_attach(chain->conn,
                     image->shmseg,
                     image->shmid,
                     0);
	  
	  image->busy = false;
      return VK_SUCCESS;		
   }

   image->pixmap = 0;
   if (chain->base.image_info.hwbuf_fd <= 0) {
      image->pixmap = xcb_generate_id(chain->conn);

      /* XCB will take ownership of the FD we pass it. */

      int fd = os_dupfd_cloexec(image->base.dma_buf_fd);
      if (fd == -1)
         return VK_ERROR_OUT_OF_HOST_MEMORY;

      xcb_dri3_pixmap_from_buffer(chain->conn,
                                  image->pixmap,
                                  chain->window,
                                  image->base.sizes[0],
                                  pCreateInfo->imageExtent.width,
                                  pCreateInfo->imageExtent.height,
                                  image->base.row_pitches[0],
                                  chain->depth, bpp, fd);
   }

   image->busy = false;
   return VK_SUCCESS;
}

static void
wsi_x11_image_finish(struct wsi_x11_swapchain *chain,
                     const VkAllocationCallbacks* pAllocator,
                     struct wsi_x11_image *image)
{
   xcb_void_cookie_t cookie;

   if (!chain->base.wsi->sw && image->pixmap) {
      cookie = xcb_free_pixmap(chain->conn, image->pixmap);
      xcb_discard_reply(chain->conn, cookie.sequence);
   }

   if (chain->base.image_info.hwbuf_fd > 0)
      close(chain->base.image_info.hwbuf_fd);

   wsi_destroy_image(&chain->base, &image->base);
#ifdef HAVE_SYS_SHM_H
   if (image->shmaddr)
      shmdt(image->shmaddr);
#endif
}

static VkResult
wsi_x11_swapchain_destroy(struct wsi_swapchain *anv_chain,
                          const VkAllocationCallbacks *pAllocator)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)anv_chain;

   if (chain->has_present_queue) {
      chain->status = VK_ERROR_OUT_OF_DATE_KHR;
      wsi_queue_push(&chain->present_queue, UINT32_MAX);
      pthread_join(chain->queue_thread, NULL);

      wsi_queue_destroy(&chain->present_queue);
   }

   for (uint32_t i = 0; i < chain->base.image_count; i++)
      wsi_x11_image_finish(chain, pAllocator, &chain->images[i]); 
  
   pthread_mutex_destroy(&chain->image_pool_mutex);
   pthread_cond_destroy(&chain->image_pool_cond);  

   pthread_mutex_destroy(&chain->present_id_mutex);
   pthread_cond_destroy(&chain->present_id_cond);

   wsi_swapchain_finish(&chain->base);

   vk_free(pAllocator, chain);

   return VK_SUCCESS;
}

static void
wsi_x11_set_mesa_drv_property(xcb_connection_t *conn,
                              xcb_window_t window)
{
   const char name[] = "_MESA_DRV";
   const char value = 0; /* Turnip */
   xcb_intern_atom_cookie_t atom_cookie;
   xcb_intern_atom_reply_t* reply;
   xcb_void_cookie_t cookie;

   atom_cookie = xcb_intern_atom(conn, 0, strlen(name), name);
   reply = xcb_intern_atom_reply(conn, atom_cookie, NULL);
   if (reply == NULL)
      return;

   cookie = xcb_change_property(conn, XCB_PROP_MODE_REPLACE,
                                window, reply->atom,
                                XCB_ATOM_CARDINAL, 8, 1, &value);

   xcb_discard_reply(conn, cookie.sequence);
   free(reply);
}


static VkResult wsi_x11_wait_for_present(struct wsi_swapchain *wsi_chain,
                                         uint64_t waitValue,
                                         uint64_t timeout)
{
   struct wsi_x11_swapchain *chain = (struct wsi_x11_swapchain *)wsi_chain;
   struct timespec abs_timespec;
   uint64_t abs_timeout = 0;

   /* Need to observe that the swapchain semaphore has been unsignalled,
    * as this is guaranteed when a present is complete. */
   VkResult result = wsi_swapchain_wait_for_present_semaphore(
      &chain->base, waitValue, timeout);

   if (result != VK_SUCCESS)
      return result;

   if (timeout != UINT64_MAX) {
      if (timeout != 0)
         abs_timeout = os_time_get_absolute_timeout(timeout);

      timespec_from_nsec(&abs_timespec, abs_timeout);
   } 

   pthread_mutex_lock(&chain->present_id_mutex);

   while (chain->present_id < waitValue) {
      int ret;
      if (timeout == UINT64_MAX)
         ret = pthread_cond_wait(&chain->present_id_cond,
                                 &chain->present_id_mutex);
      else
         ret = pthread_cond_timedwait(&chain->present_id_cond,
                                      &chain->present_id_mutex,
                                      &abs_timespec);
      if (ret == ETIMEDOUT) {
         result = VK_TIMEOUT;
         break;
      }
      else if (ret) {
         result = VK_ERROR_DEVICE_LOST;
         break;
      }
   }

   pthread_mutex_unlock(&chain->present_id_mutex);

   if (result == VK_SUCCESS && chain->status < 0)
      result = chain->status;
  
   return result;
}

static void wsi_x11_get_hwbuf_info(xcb_connection_t *conn, xcb_window_t window, int* outFd, uint16_t* outStride) 
{
   xcb_dri3_buffer_from_pixmap_cookie_t cookie;
   xcb_dri3_buffer_from_pixmap_reply_t *reply;
   int fd = -1;
   uint16_t stride = 0;

   cookie = xcb_dri3_buffer_from_pixmap(conn, window);
   reply = xcb_dri3_buffer_from_pixmap_reply(conn, cookie, NULL);

   if (reply) {
      int *fds;
      fds = xcb_dri3_buffer_from_pixmap_reply_fds(conn, reply);
      fd = fds[0];
      stride = reply->stride;
      free(reply);
   }

   *outFd = fd;
   *outStride = stride;
}

static VkResult
wsi_x11_surface_create_swapchain(VkIcdSurfaceBase *icd_surface,
                                 VkDevice device,
                                 struct wsi_device *wsi_device,
                                 const VkSwapchainCreateInfoKHR *pCreateInfo,
                                 const VkAllocationCallbacks* pAllocator,
                                 struct wsi_swapchain **swapchain_out)
{
   struct wsi_x11_swapchain *chain;
   xcb_void_cookie_t cookie;
   VkResult result;
   VkPresentModeKHR present_mode = wsi_swapchain_get_present_mode(wsi_device, pCreateInfo);

   assert(pCreateInfo->sType == VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR);

   xcb_connection_t *conn = wsi_x11_surface_get_connection(icd_surface);
   struct wsi_x11_connection *wsi_conn =
      wsi_x11_get_connection(wsi_device, conn);
   if (!wsi_conn)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   xcb_window_t window = wsi_x11_surface_get_window(icd_surface);

   xcb_get_geometry_reply_t *geom =
      xcb_get_geometry_reply(conn, xcb_get_geometry(conn, window), NULL);
   if (geom == NULL)
      return VK_ERROR_SURFACE_LOST_KHR;
   const uint32_t bit_depth = geom->depth;
   const uint16_t cur_width = geom->width;
   const uint16_t cur_height = geom->height;
   free(geom);

   /* Allocate the actual swapchain. The size depends on image count. */
   size_t size = sizeof(*chain) + pCreateInfo->minImageCount * sizeof(chain->images[0]);
   chain = vk_zalloc(pAllocator, size, 8,
                     VK_SYSTEM_ALLOCATION_SCOPE_OBJECT);
   if (chain == NULL)
      return VK_ERROR_OUT_OF_HOST_MEMORY;

   int ret;
   bool bret;

   ret = pthread_mutex_init(&chain->image_pool_mutex, NULL);
   if (ret != 0) {
      vk_free(pAllocator, chain);
      return VK_ERROR_OUT_OF_HOST_MEMORY;
   }

   bret = wsi_init_pthread_cond_monotonic(&chain->image_pool_cond);
   if (!bret) {
      pthread_mutex_destroy(&chain->image_pool_mutex);
      vk_free(pAllocator, chain);
      return VK_ERROR_OUT_OF_HOST_MEMORY;
   }

   ret = pthread_mutex_init(&chain->present_id_mutex, NULL);
   if (ret != 0) {
      vk_free(pAllocator, chain);
      return VK_ERROR_OUT_OF_HOST_MEMORY;
   }

   bret = wsi_init_pthread_cond_monotonic(&chain->present_id_cond);
   if (!bret) {
      pthread_mutex_destroy(&chain->present_id_mutex);
      vk_free(pAllocator, chain);
      return VK_ERROR_OUT_OF_HOST_MEMORY;
   } 

   struct wsi_base_image_params *image_params = NULL;
   struct wsi_cpu_image_params cpu_image_params;
   struct wsi_drm_image_params drm_image_params;

   if (wsi_device->sw) {
      cpu_image_params = (struct wsi_cpu_image_params) {
         .base.image_type = WSI_IMAGE_TYPE_CPU
      };
      image_params = &cpu_image_params.base;
   } else {
      drm_image_params = (struct wsi_drm_image_params) {
         .base.image_type = WSI_IMAGE_TYPE_DRM,
         .same_gpu = true,
      };
      if (wsi_device->supports_modifiers) {
         const uint64_t *modifiers[2] = {NULL, NULL};
         const uint32_t num_modifiers[2] = {0, 0};

         drm_image_params.num_modifier_lists = 0;
         drm_image_params.num_modifiers = num_modifiers;
         drm_image_params.modifiers = (const uint64_t **)modifiers;
      }
      image_params = &drm_image_params.base;
   }

   result = wsi_swapchain_init(wsi_device, &chain->base, device, pCreateInfo,
                               image_params, pAllocator);

   if (result != VK_SUCCESS)
      goto fail_alloc;

   chain->base.destroy = wsi_x11_swapchain_destroy;
   chain->base.get_wsi_image = wsi_x11_get_wsi_image;
   chain->base.acquire_next_image = wsi_x11_acquire_next_image;
   chain->base.queue_present = wsi_x11_queue_present;

   if (!wsi_device->sw)
      chain->base.wait_for_present = wsi_x11_wait_for_present;

   chain->base.release_images = wsi_x11_release_images;
   chain->base.present_mode = present_mode;
   chain->base.image_count = pCreateInfo->minImageCount;
   chain->conn = conn;
   chain->window = window;
   chain->depth = bit_depth;
   chain->extent = pCreateInfo->imageExtent;
   chain->has_present_queue = false;
   chain->present_id = 0;
   chain->status = VK_SUCCESS;
   chain->has_mit_shm = wsi_conn->has_mit_shm;

   if (chain->extent.width != cur_width || chain->extent.height != cur_height)
       chain->status = VK_SUBOPTIMAL_KHR;

   if (wsi_x11_use_hwbuf()) {
      uint16_t hwbuf_stride;
      wsi_x11_get_hwbuf_info(chain->conn, chain->window, &chain->base.image_info.hwbuf_fd, &hwbuf_stride);
      if (hwbuf_stride > 0) chain->base.image_info.create.extent.width = hwbuf_stride;
   }
   else
      chain->base.image_info.hwbuf_fd = -1;

   if (chain->base.image_info.hwbuf_fd <= 0 && !wsi_device->sw) {
      cookie = xcb_present_select_input(chain->conn, 0,
                                        chain->window,
                                        XCB_PRESENT_EVENT_MASK_NO_EVENT);
      xcb_discard_reply(chain->conn, cookie.sequence);
   }

   if (wsi_device->sw) {
      /* Create the graphics context. */
      chain->gc = xcb_generate_id(chain->conn);
      if (!chain->gc) {
         result = VK_ERROR_OUT_OF_HOST_MEMORY;
         goto fail_register;
      }

      cookie = xcb_create_gc(chain->conn,
                             chain->gc,
                             chain->window,
                             XCB_GC_GRAPHICS_EXPOSURES,
                             (uint32_t []) { 0 });
      xcb_discard_reply(chain->conn, cookie.sequence);
   }

   uint32_t image = 0;
   for (; image < chain->base.image_count; image++) {
      result = wsi_x11_image_init(device, chain, pCreateInfo, pAllocator,
                                  &chain->images[image]);
      if (result != VK_SUCCESS)
         goto fail_init_images;
   }

   if (chain->base.present_mode == VK_PRESENT_MODE_MAILBOX_KHR && !wsi_device->sw) {
      chain->has_present_queue = true;

      /* The queues have a length of base.image_count + 1 because we will
       * occasionally use UINT32_MAX to signal the other thread that an error
       * has occurred and we don't want an overflow.
       */
      int ret;
      ret = wsi_queue_init(&chain->present_queue, chain->base.image_count + 1);
      if (ret)
         goto fail_init_images;

      ret = pthread_create(&chain->queue_thread, NULL,
                           wsi_x11_present_queue_thread, chain);
      if (ret) {
         wsi_queue_destroy(&chain->present_queue);

         goto fail_init_images;
      }
   }

   wsi_x11_set_mesa_drv_property(conn, window);

   *swapchain_out = &chain->base;

   return VK_SUCCESS;

fail_init_images:
   for (uint32_t j = 0; j < image; j++)
      wsi_x11_image_finish(chain, pAllocator, &chain->images[j]);

fail_register:
   wsi_swapchain_finish(&chain->base);

fail_alloc:
   vk_free(pAllocator, chain);

   return result;
}

VkResult
wsi_x11_init_wsi(struct wsi_device *wsi_device,
                 const VkAllocationCallbacks *alloc,
                 const struct driOptionCache *dri_options)
{
   struct wsi_x11 *wsi;
   VkResult result;

   wsi = vk_alloc(alloc, sizeof(*wsi), 8,
                   VK_SYSTEM_ALLOCATION_SCOPE_INSTANCE);
   if (!wsi) {
      result = VK_ERROR_OUT_OF_HOST_MEMORY;
      goto fail;
   }

   int ret = pthread_mutex_init(&wsi->mutex, NULL);
   if (ret != 0) {
      result = VK_ERROR_OUT_OF_HOST_MEMORY;

      goto fail_alloc;
   }

   wsi->connections = _mesa_hash_table_create(NULL, _mesa_hash_pointer,
                                              _mesa_key_pointer_equal);
   if (!wsi->connections) {
      result = VK_ERROR_OUT_OF_HOST_MEMORY;
      goto fail_mutex;
   }

   wsi->base.get_support = wsi_x11_surface_get_support;
   wsi->base.get_capabilities2 = wsi_x11_surface_get_capabilities2;
   wsi->base.get_formats = wsi_x11_surface_get_formats;
   wsi->base.get_formats2 = wsi_x11_surface_get_formats2;
   wsi->base.get_present_modes = wsi_x11_surface_get_present_modes;
   wsi->base.get_present_rectangles = wsi_x11_surface_get_present_rectangles;
   wsi->base.create_swapchain = wsi_x11_surface_create_swapchain;

   wsi_device->wsi[VK_ICD_WSI_PLATFORM_XCB] = &wsi->base;
   wsi_device->wsi[VK_ICD_WSI_PLATFORM_XLIB] = &wsi->base;

   return VK_SUCCESS;

fail_mutex:
   pthread_mutex_destroy(&wsi->mutex);
fail_alloc:
   vk_free(alloc, wsi);
fail:
   wsi_device->wsi[VK_ICD_WSI_PLATFORM_XCB] = NULL;
   wsi_device->wsi[VK_ICD_WSI_PLATFORM_XLIB] = NULL;

   return result;
}

void
wsi_x11_finish_wsi(struct wsi_device *wsi_device,
                   const VkAllocationCallbacks *alloc)
{
   struct wsi_x11 *wsi =
      (struct wsi_x11 *)wsi_device->wsi[VK_ICD_WSI_PLATFORM_XCB];

   if (wsi) {
      hash_table_foreach(wsi->connections, entry)
         wsi_x11_connection_destroy(wsi_device, entry->data);

      _mesa_hash_table_destroy(wsi->connections, NULL);

      pthread_mutex_destroy(&wsi->mutex);

      vk_free(alloc, wsi);
   }
}
