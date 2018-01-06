# For python3, linux I did:
# pip install Pillow
# apt-get install python3-tk
# apt-get install python3-cairo
# pip install cairocffi

import argparse
import collections
import datetime
import math
import time

from tkinter import Tk, Label
from PIL import Image, ImageTk
import cairocffi as cairo

import common
import testplugin
import timelineplugin
from config import cfg

BoundingBox = collections.namedtuple("BoundingBox", ["left","top","width",
    "height"])

class CairoUtils(object):

    @staticmethod
    def set_fill_params(context, fill_params):
        """ Set context to fill_params. """
        context.set_source_rgba(*fill_params.colour)

    @staticmethod
    def set_stroke_params(context, stroke_params):
        """ Set context to stroke_params. """
        context.set_source_rgba(*stroke_params.colour)
        context.set_line_width(stroke_params.line_width)
        context.set_dash(*stroke_params.dash_style)
        context.set_line_cap(stroke_params.line_cap)

    @staticmethod
    def draw(context, params):
        """ Draw fill and/or stroke with params. """
        if params.fill and params.stroke:
            CairoUtils.set_fill_params(context, params.fill)
            context.fill_preserve()
            CairoUtils.set_stroke_params(context, params.stroke)
            context.stroke()
        elif params.fill:
            CairoUtils.set_fill_params(context, params.fill)
            context.fill()
        elif params.stroke:
            CairoUtils.set_stroke_params(context, params.stroke)
            context.stroke()

    @staticmethod
    def get_square_box(bounding_box):
        """ Return largest square in the bounding box """
        bb = bounding_box
        box_size = min(bb.width, bb.height)
        result = BoundingBox(
            left=bb.left + (bb.width - box_size) / 2,
            top=bb.top + (bb.height - box_size) / 2,
            width=box_size,
            height=box_size)
        return result

    @staticmethod
    def get_margin_box(bounding_box, margin):
        """ Return bounding box with margin removed. """
        print(bounding_box)
        bb = bounding_box
        print(bb)
        print(bb.left)
        print(margin)
        result = BoundingBox(
            left=bb.left + margin,
            top=bb.top + margin,
            width=bb.width - 2 * margin,
            height=bb.height - 2 * margin)
        return result

    @staticmethod
    def move_to_points(context, points):
        for point in points:
            context.line_to(*point)

class ContextRestorer(object):

    def __init__(self, context):
        self._context = context
        self._matrix = None

    def __enter__(self):
        self._matrix = self._context.get_matrix()
        return None

    def __exit__(self, type, value, traceback):
        self._context.set_matrix(self._matrix)

class Clock(object):

    def __init__(self, bounding_box):
        margin_bb = CairoUtils.get_margin_box(
            bounding_box=bounding_box,
            margin=cfg.clock.margin)
        self._real_bb = CairoUtils.get_square_box(margin_bb)
        self._unit = self._real_bb.width

    def render(self, context, now):

        with ContextRestorer(context):

            # Translate to middle of clock face.
            context.translate(
                self._real_bb.left + self._real_bb.width / 2,
                self._real_bb.top + self._real_bb.height / 2)

            # Draw ticks.
            for i in range(0, 60):

                if (i % 5) == 0:
                    tick_params = cfg.clock.hour_ticks
                else:
                    tick_params = cfg.clock.minute_ticks

                self.draw_tick(context, i, 60, tick_params)

            # Draw hour hand.
            self.draw_hand(context, now.hour * 60 + now.minute, 12 * 60, cfg.clock.hour_hand)

            # Draw minute hand.
            self.draw_hand(context, now.minute, 60, cfg.clock.minute_hand)

    def draw_tick(self, context, num, den, params):

        with ContextRestorer(context):
            rotation = (2 * math.pi) * (num / den)
            context.rotate(rotation)

            context.rectangle(-(self._unit * params.thickness_pc) / 2,
                              self._unit / 2 - (self._unit * params.depth_pc),
                              self._unit * params.thickness_pc,
                              self._unit * params.depth_pc)

            CairoUtils.draw(context, params)

    def draw_hand(self, context, num, den, params):

        with ContextRestorer(context):
            rotation = (2 * math.pi) * (num / den)
            context.rotate(rotation)

            context.rectangle(
                -(self._unit * params.thickness_pc) / 2,
                -(self._unit * params.front_depth_pc),
                 (self._unit * params.thickness_pc),
                 (self._unit * (params.front_depth_pc
                    + params.back_depth_pc)))

            CairoUtils.draw(context, params)

class Timeline(object):

    def __init__(self, bounding_box):

        self._bb = CairoUtils.get_square_box(
            CairoUtils.get_margin_box(
                bounding_box=bounding_box,
                margin=cfg.timeline.margin))
        self._unit = self._bb.width
        self._centre = (self._bb.left + self._bb.width / 2,
                        self._bb.top + self._bb.height / 2)

    def datetime_to_t(self, datetime):
        return 2 * math.pi * (datetime.hour * 60 + datetime.minute) / (12 * 60)

    def timedelta_to_t(self, timedelta):
        return 2*math.pi*timedelta.total_seconds() / (12 * 60 * 60)

    def get_spiral_params(self, offset, now):
        """
        Calculate the parameters a,b to the spiral described by
            x = (a * t + b) * math.sin(c * t + d)
            y = (a * t + b) * math.cos(c * t + d)
        where t=0 is closest to the edge of the clock face and every increment
        of 2*math.pi corresponds to one rotation of the clock face.
        """
        margin = cfg.timeline.margin
        thickness = cfg.timeline.thickness

        start_angle = self.datetime_to_t(now)
        max_radius = (self._unit / 2) - margin - offset

        # Parameter 'a' corresponds to minus one 'thickness' per rotation.
        a = -thickness / (2 * math.pi)
        b = max_radius
        c = -1.0
        d = math.pi - start_angle

        return (a, b, c, d)

    def get_spiral_point(self, spiral_params, t):
        scalar = spiral_params[0] * t + spiral_params[1]
        angle = spiral_params[2] * t + spiral_params[3]
        x = scalar * math.sin(angle)
        y = scalar * math.cos(angle)

        return (self._centre[0] + x, self._centre[1] + y)

    def get_spiral_points(self, spiral_params, t_min, t_max):
        result = []
        t = t_min
        while t < t_max:
            point = self.get_spiral_point(spiral_params, t)
            result.append(point)
            t += 0.1

        point = self.get_spiral_point(spiral_params, t_max)
        result.append(point)

        return result

    def render(self, context, now):

        #context.translate(*self._centre)
        thickness = cfg.timeline.thickness
        length = cfg.timeline.length

        t_min = 0
        t_max = (length.total_seconds() / (12 * 60 * 60)) * 2 * math.pi

        #print("t_min={}".format(t_min))
        #print("t_max={}".format(t_max))

        separator_spiral_params = self.get_spiral_params(offset=thickness, now=now)
        separator_spiral_points = self.get_spiral_points(separator_spiral_params, t_min, t_max)
        CairoUtils.move_to_points(context, separator_spiral_points)
        CairoUtils.set_stroke_params(context, cfg.timeline.stroke)
        context.stroke()

        labels_spiral_params = self.get_spiral_params(offset=thickness/2, now=now)

        # Find next
        floored_now = now.replace(hour=now.hour//3*3, minute=0, second=0, microsecond=0)
        print("floored_now={}".format(floored_now))

        context.set_font_size(10)

        now_t = self.datetime_to_t(now)
        i = 1

        while True:

            label_datetime = floored_now + datetime.timedelta(hours=3*i)
            if label_datetime > now + length:
                break

            label_secs = (label_datetime - now).total_seconds()
            label_hours = 12 * int(label_secs // (12 * 60 * 60)) % (12 * 60 * 60)

            if label_hours > 0:
                    label_text = "+{}h".format(label_hours)

                    #if label_days == 0:
                    #    label_text = '{}h {}m'.format(label_hours, label_mins)
                    #else:
                    #    label_text = '{}d {}h'.format(label_days, label_hours)

                    _, _, w, h, _, _ = context.text_extents(label_text)
                    #print("w={}".format(w))
                    #print("h={}".format(h))

                    #print("label_datetime={}".format(label_datetime))
                    label_timedelta = label_datetime - now
                    #print("label_timedelta={}".format(label_timedelta))
                    label_t = self.timedelta_to_t(label_timedelta)
                    #print("label_t={}".format(label_t ))

                    #print(floored_now_t)


                    label_point = self.get_spiral_point(labels_spiral_params, label_t)#

                    with ContextRestorer(context):
                        context.translate(label_point[0], label_point[1])
                        context.rotate(now_t + label_t)
                        context.move_to(-w/2, h/2)
                        context.show_text(label_text)

            #context.arc(*label_point, 5, 0, 2*math.pi)
            #context.stroke()
            i += 1

        #floored_now_plus_15 = floored_now + datetime.timedelta(minute=15)




        '''
        points = self.spiral_line_generator(offset=7.5)
        CairoUtils.move_to_points(context, points)
        context.set_source_rgba(1, 0, 0, 1)
        context.set_line_width(8)
        context.set_dash([],0)
        context.stroke()

        points = self.spiral_line_generator(offset=17.5)
        CairoUtils.move_to_points(context, points)
        context.set_source_rgba(1, 1, 0, 1)
        context.set_line_width(8)
        context.set_dash([],0)
        context.stroke()
        '''
        '''
        radius = self._unit / 2

        segments = self._params['timeline']['segments']

        base_start_angle = -0.5 * math.pi
        base_end_angle = base_start_angle + 2 * math.pi

        previous_radius = None

        def get_angle(angle, radius, approx_offset):
            return angle + math.atan(approx_offset / radius)

        def get_point(angle, radius):
            return (self._centre[0] + math.cos(angle) * radius, \
                    self._centre[1] + math.sin(angle) * radius)

        for segment in segments[::-1]:

            radius -= segment['thickness']


            #end_angle_delta = math.atan(2*segment['thickness']/radius)
            #end_angle = start_angle + 2 * math.pi - end_angle_delta

            #control_point_angle_delta = math.atan(segment['thickness']/radius)
            #control_point_angle = start_angle + 2 * math.pi - control_point_angle_delta

            if previous_radius:
                # Draw join to previous curve.
                control_point1 = get_point(get_angle(base_end_angle, previous_radius, -5), previous_radius)
                control_point2 = get_point(get_angle(base_end_angle, radius, -5), radius)
                end_point = get_point(base_start_angle, radius)
                context.curve_to(*control_point1, *control_point2, *end_point)



            # Draw the main arc.
            arc_start_angle = base_start_angle
            arc_end_angle = get_angle(base_end_angle, radius, -10)
            context.arc(*self._centre, radius, arc_start_angle, arc_end_angle)

            # Remember for next round!
            previous_radius = radius


        CairoUtils.set_stroke_params(context, self._params['timeline']['stroke'])
        context.stroke()

        for plugin in self._params['plugins']:
            assert(isinstance(plugin, timelineplugin.TimelinePlugin))

            end_delta = datetime.timedelta(hours=12*len(segments))
            timeline_items = plugin.get_timeline_items(now, now + end_delta)

            for timeline_item in timeline_items:
                assert(isinstance(timeline_item, timelineplugin.TimelineItem))

                item_start = timeline_item.start()
                item_end = timeline_item.end()

                arcs = []

                segment_start = now.replace(hour=now.hour%2, minute=0, second=0, microsecond=0)
                segment_end = segment_start + datetime.timedelta(hours=12)
                segment_radius = self._clock_unit / 2

                base_angle = (2 * math.pi * (now.hour * 60 + now.minute)) / (12 * 60)

                for segment in self._params['timeline']['segments']:

                    if not (item_end <= segment_start or item_start >= segment_end):
                        start = max(item_start, segment_start)
                        end = min(item_end, segment_end)

                        multiplier = 2 * math.pi / (12 * 60 * 60)

                        start_angle = multiplier * (start - segment_start).total_seconds()
                        end_angle = multiplier * (end - segment_start   ).total_seconds()

                        arc = common.ArcParams(
                            centre=self._centre,
                            radius=segment_radius + segment['thickness']/2,
                            start_angle=base_angle + start_angle,
                            end_angle=base_angle + end_angle)

                        arcs.append(arc)

                    segment_start = segment_end
                    segment_end = segment_start + datetime.timedelta(hours=12)
                    segment_radius += segment['thickness']

                plugin.render_on_clockface(context, timeline_items, arcs)
        '''

class ExampleGui(Tk):
    def __init__(self, debug, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not debug:
            super().attributes("-fullscreen", True)
            super().config(cursor="none")

        self.size = cfg.window.width, cfg.window.height

        self.geometry("{}x{}".format(*self.size))

        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *self.size)
        self.context = cairo.Context(self.surface)


        # Draw something
        #self.context.scale(w, h)

        #self.context.set_source_rgba(1, 0, 0, 1)
        #self.context.move_to(90, 140)
        #self.context.rotate(-0.5)
        #self.context.set_font_size(32)
        #self.context.show_text(u'HAPPY DONUT!')

        bounding_box = BoundingBox(
            left=20,
            top=20,
            width=440,
            height=440)


        self._clock = Clock(bounding_box)
        self._timeline = Timeline(bounding_box)

        #self.render()
        #self._image_ref = ImageTk.PhotoImage(Image.frombuffer("RGBA", (w, h), self.surface.get_data(), "raw", "BGRA", 0, 1))

        self.label = Label(self)
        self.label.pack(expand=True, fill="both")

        while True:
            self.render()
            self.update_idletasks()
            self.update()
            time.sleep(5)

    def render(self):

        now = datetime.datetime.now()

        self.context.set_operator(cairo.constants.OPERATOR_OVER)

        self.context.rectangle(0, 0, *self.size)
        self.context.set_source_rgba(*cfg.window.background_colour)
        self.context.fill()

        #self.context.set_operator(cairo.constants.OPERATOR_SCREEN)

        self._clock.render(self.context, now)
        self._timeline.render(self.context, now)

        new_img = Image.frombuffer("RGBA", self.size,
                                   self.surface.get_data(),
                                   "raw","BGRA", 0, 1)
        new_tk_img = ImageTk.PhotoImage(new_img)

        self.label.configure(image=new_tk_img)
        self.label.image = new_tk_img
        #panel.image = img2




if __name__ == "__main__":
    """
    Using the argparse module to ease the development process of this source
    code a little. Start this file with command-line argument '--mode debug' to
    avoid going in fullscreen mode and to avoid hiding the cursor.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['release', 'debug'], default='release')

    args = parser.parse_args()

    ExampleGui(debug=(args.mode == 'debug'))
