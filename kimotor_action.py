import wx
import pcbnew
import os
import numpy as np
import math

if __name__ == '__main__':
    import kimotor_gui
    import kimotor_fillet as kf
    import kimotor_linalg as kla
else:
    from . import kimotor_gui
    from . import kimotor_fillet as kf
    from . import kimotor_linalg as kla

class KiMotor(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "KiMotor"
        self.category = "Modify Drawing PCB"
        self.description = "KiMotor - Design of parametric axial-flux motor stators"
        self.show_toolbar_button = True # Optional, defaults to False
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'flexibility.png') # Optional, defaults to ""

    def Run( self ):
        # grab editor frame and board
        self.frame = wx.FindWindowByName("PcbFrame")
        self.board = pcbnew.GetBoard()
        
        dlg = KiMotorDialog(self.frame, self.board)
        dlg.Show()


class KiMotorDialog ( kimotor_gui.KiMotorGUI ):
     
    def __init__(self,  parent, board):
        kimotor_gui.KiMotorGUI.__init__(self, parent)
        self.board = board

        self.poles = 0
        self.loops = 0
        self.trk_w = 0
        self.r_fill = 0
        self.r_flat = 0
        self.do = 0
        self.di = 0
        self.db = 0

    # event handlers
    def on_btn_clear(self, event):
        #self.logger.info("Cleared existing coils")
        #logging.shutdown()
        #self.Close()
        event.Skip()

    def on_btn_generate(self, event):
        #self.logger.info("Generate stator coils")
        self.generate()
        event.Skip()

    def generate(self):

        # get gui values
        # units (mm converted to nm sometimes)
        self.poles = int(self.m_ctrlPoles.GetValue())
        self.loops = int(self.m_ctrlLoops.GetValue())

        self.trk_w = int(self.m_ctrlTrackWidth.GetValue() * 1e6) # track width
        self.dr = self.trk_w * 2    # track gaps
        self.r_fill = int(self.m_ctrlRfill.GetValue() * 1e6)
        self.r_flat = int(self.m_ctrlRflatt.GetValue() * 1e6)
        self.ro = int(self.m_ctrlDout.GetValue() * 1e6 / 2)
        self.ri = int(self.m_ctrlDin.GetValue() * 1e6 / 2)
        self.rb = int(self.m_ctrlDbore.GetValue() * 1e6 / 2)


        self.group = pcbnew.PCB_GROUP( self.board )
        self.board.Add(self.group)

        # generate coils
        coil_t = self.do_coils()
        # connect coils
        self.do_coils_terminals(coil_t, self.dr, 3*self.dr)
        # place mounting holes
        self.do_mounts()
        # design the board edges
        self.do_outline( 1.1*self.ro, self.rb )

        # update board
        pcbnew.Refresh()


    # helpers
    def coil_solver(self, r1,r2, dr0, dr,th,turns):
        
        pts = []
        mds = []

        # points 
        c = [0,0,0]
        l0 = np.array([ c, [r1*math.cos(th/2), r1*math.sin(th/2), 0] ])
        l0 = kla.line_offset(l0, -dr0)

        for l in range(turns):
            # offset line
            lr = kla.line_offset(l0, -l*dr)
            # solve corners
            pc1 = kla.circle_line_intersect(lr, c, r1+l*dr)
            pc1 = pc1[0:2]
            pc2 = kla.circle_line_intersect(lr, c, r2-l*dr)
            pc2 = pc2[0:2]
            pc3 = np.array([ pc2[0],-pc2[1] ])
            pc4 = np.array([ pc1[0],-pc1[1] ])
            # solve outer mid point
            pm = np.array([ r2-l*dr, 0 ])
            
            pts.extend([pc1, pc2, pc3, pc4])
            mds.extend([pm])

        pm = np.matrix(pts)   # points, excl. arc mids
        mm = np.matrix(mds) # arc mids only

        return pm, mm

    def do_coils(self):

        # coil terminals
        coil_t = []

        try:
            if self.ri < self.rb*1.5:
                raise ValueError()
        except ValueError:
            wx.LogWarning('Coil inner side and shaft bore are too close. Must be D_in > 1.5*D_bore')
            return

        # TODO: set min distance depending on voltage?
        dr = self.trk_w * 2
        
        th0 = math.radians(360/self.poles)

        # limit coil base width (assume 1deg gap between coils base)
        #dth = math.radians(0.5)
        # coil base half-width 
        #w2 = 10 * 1e6 #ri * math.cos(th0/2 - dth)

        # coil (corners, mid-points)
        pcum, pcumm = self.coil_solver(self.ri, self.ro, dr, dr, th0, self.loops)

        # poles
        for p in range(self.poles):

            # rotation matrix
            th = th0 * p + math.radians(0.0001);
            c = math.cos(th)
            s = math.sin(th)
            R = np.array( [[c, -s],[s, c]] )
            # rotate all coil points
            Tf = np.matmul(R, pcum.transpose()).transpose()
            Tfv = np.matmul(R, pcumm.transpose()).transpose()

            # draw tracks
            startf = Tf[0]
            iv = 0
            
            # store 1st coil terminal
            cs = pcbnew.wxPoint( int(startf[0,0].item()), int(startf[0,1].item()) )
            
            for idx, tf in enumerate(Tf[1:]):
                
                # start point, end point of track segment
                ps = pcbnew.wxPoint( int(startf[0,0].item()), int(startf[0,1].item()) )
                pe = pcbnew.wxPoint( int(tf[0,0].item()), int(tf[0,1].item()) ) 

                # use arc for the coil outer side
                if not (idx-1)%4:
                    t_fcu = pcbnew.PCB_ARC(self.board)
                    tfv = Tfv[iv]
                    iv += 1
                    mp = pcbnew.wxPoint( tfv[0,0], tfv[0,1])
                    t_fcu.SetMid( mp  )

                else:
                    t_fcu = pcbnew.PCB_TRACK(self.board)    
                
                t_fcu.SetWidth( self.trk_w )
                t_fcu.SetLayer(pcbnew.F_Cu)
                t_fcu.SetStart( ps )
                t_fcu.SetEnd( pe )
                self.board.Add(t_fcu)
                self.group.AddItem(t_fcu)
                
                # fillet
                if idx > 0 and self.r_fill > 0:
                    kf.fillet(self.board, track0f, t_fcu, self.r_fill)

                track0f = t_fcu    
                startf = tf


            # startb = Tb[0]
            # iv = 0
            # for idx, tb in enumerate(Tb[1:]):
                
            #     # start point, end point of track segment
            #     ps = pcbnew.wxPoint( int(startb[0,0].item()), int(startb[0,1].item()) )
            #     pe = pcbnew.wxPoint( int(tb[0,0].item()), int(tb[0,1].item()) ) 

            #     # use arc for the coil outer side
            #     if not (idx-1)%4 and use_arc:
            #         t_bcu = pcbnew.PCB_ARC(self.board)
            #         tbv = Tbv[iv]
            #         iv += 1
            #         t_bcu.SetMid( pcbnew.wxPoint( tbv[0,0].item(), tbv[0,1].item()) )
            #     else:
            #         t_bcu = pcbnew.PCB_TRACK(self.board)    
                
            #     t_bcu.SetWidth( self.trk_w )
            #     t_bcu.SetLayer(pcbnew.B_Cu)
            #     t_bcu.SetStart( ps )
            #     t_bcu.SetEnd( pe )
            #     self.board.Add(t_bcu)
            #     self.group.AddItem(t_bcu)
                
            #     # fillet
            #     if idx > 0 and self.r_fill > 0:
            #         kf.fillet(self.board, track0b, t_bcu, self.r_fill)

            #     track0b = t_bcu    
            #     startb = tb


            # TODO: logic for connecting layers
            
            # store 2nd coil terminal
            ce = pcbnew.wxPoint( int(startf[0,0].item()), int(startf[0,1].item()) )
            coil_t.append([cs,ce])

        # pass coil terminals
        return coil_t

    def do_coils_terminals(self, coil_t, dr, dri):
        # start with a simple 6-pole, 3-phase connections
        # draw terminals 
        
        # dr: spacing between connection rings
        # dri: spacing between connection rings
        th0 = math.radians(360/self.poles)

        # coil terminals
        delta_c = []

        # rot adj (manual) to make jumper parallel to coil sides
        thadj = math.radians(10)

        for p in range(3):
            
            # concentric rings/arcs
            crb = self.rb + dri + p*dr
            cro = (self.ro + dri + p*dr)

            # start, end, and mid angle
            ths = th0*p + thadj
            the = ths + 2/3*math.pi + thadj
            thm = (ths+the)/2

            # get coils terminals
            # TODO: generalize
            c1s, c1e = coil_t[p]
            c2s, c2e = coil_t[p+3]

            # inner rings
            rs = pcbnew.wxPoint( crb*math.cos(ths), crb*math.sin(ths) )
            re = pcbnew.wxPoint( crb*math.cos(the), crb*math.sin(the) )
            rm = pcbnew.wxPoint( crb*math.cos(thm), crb*math.sin(thm) )

            conn = pcbnew.PCB_ARC(self.board)
            conn.SetLayer(pcbnew.F_Cu)
            conn.SetWidth(self.trk_w)
            conn.SetStart( rs )
            conn.SetMid( rm )
            conn.SetEnd( re )
            self.board.Add(conn)
            self.group.AddItem(conn)

            # inner juncion start (opposite side)
            conn = pcbnew.PCB_TRACK(self.board)
            conn.SetLayer(pcbnew.B_Cu)
            conn.SetWidth(self.trk_w)
            conn.SetStart( c1s )
            conn.SetEnd( rs )
            self.board.Add(conn)
            self.group.AddItem(conn)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( c1s )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( rs )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            # inner juncion end (opposite side)
            conn = pcbnew.PCB_TRACK(self.board)
            conn.SetLayer(pcbnew.B_Cu)
            conn.SetWidth(self.trk_w)
            conn.SetStart( re )
            conn.SetEnd( c2s )
            self.board.Add(conn)
            self.group.AddItem(conn)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( re )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( c2s )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)


            # outer rings (motor terminals are the start of these arcs)
            the = ths + thadj
            ths = - (3-p) * math.radians(5) + thadj 
            thm = (ths+the)/2
            
            rs = pcbnew.wxPoint( cro*math.cos(ths), cro*math.sin(ths) )
            rm = pcbnew.wxPoint( cro*math.cos(thm), cro*math.sin(thm) )
            re = pcbnew.wxPoint( cro*math.cos(the), cro*math.sin(the) )

            conn = pcbnew.PCB_ARC(self.board)
            conn.SetLayer(pcbnew.F_Cu)
            conn.SetWidth(self.trk_w)
            conn.SetStart( rs )
            conn.SetMid( rm )
            conn.SetEnd( re )
            self.board.Add(conn)
            self.group.AddItem(conn)

            # inner juncion end (opposite side)
            conn = pcbnew.PCB_TRACK(self.board)
            conn.SetLayer(pcbnew.B_Cu)
            conn.SetWidth(self.trk_w)
            conn.SetStart( re )
            conn.SetEnd( c1e )
            self.board.Add(conn)
            self.group.AddItem(conn)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( re )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( c1e )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)


            # coil delta connection terminal
            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( c2e )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            # store terminal for the jummper track
            delta_c.append(c2e)

            # motor terminal
            via = pcbnew.PCB_VIA(self.board)
            via.SetPosition( rs )
            via.SetDrill( int(self.trk_w/2) )
            via.SetWidth( int(self.trk_w) )
            self.board.Add(via)
            self.group.AddItem(via)

            #wx.LogWarning(f'points: {c1s} {c2s}')

            #a_v = pcbnew.VECTOR2I(
            #   (a_e.x - a_s.x) * a_reverse,
            #    -(a_e.y - a_s.y) * a_reverse
            #)

        # create delta connection
        ths = th0 * 3 + thadj
        the = th0 * 5 + thadj
        thm = (the+ths)/2

        rs = pcbnew.wxPoint( cro*math.cos(ths), cro*math.sin(ths) )
        rm = pcbnew.wxPoint( cro*math.cos(thm), cro*math.sin(thm) )
        re = pcbnew.wxPoint( cro*math.cos(the), cro*math.sin(the) )

        conn = pcbnew.PCB_ARC(self.board)
        conn.SetLayer(pcbnew.F_Cu)
        conn.SetWidth(self.trk_w)
        conn.SetStart( rs )
        conn.SetMid( rm )
        conn.SetEnd( re )
        self.board.Add(conn)
        self.group.AddItem(conn)

        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition( rs )
        via.SetDrill( int(self.trk_w/2) )
        via.SetWidth( int(self.trk_w) )
        self.board.Add(via)
        self.group.AddItem(via)

        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition( rm )
        via.SetDrill( int(self.trk_w/2) )
        via.SetWidth( int(self.trk_w) )
        self.board.Add(via)
        self.group.AddItem(via)

        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition( re )
        via.SetDrill( int(self.trk_w/2) )
        via.SetWidth( int(self.trk_w) )
        self.board.Add(via)
        self.group.AddItem(via)

        
        conn = pcbnew.PCB_TRACK(self.board)
        conn.SetLayer(pcbnew.B_Cu)
        conn.SetWidth(self.trk_w)
        conn.SetStart( rs )
        conn.SetEnd( delta_c[0] )
        self.board.Add(conn)
        self.group.AddItem(conn)

        conn = pcbnew.PCB_TRACK(self.board)
        conn.SetLayer(pcbnew.B_Cu)
        conn.SetWidth(self.trk_w)
        conn.SetStart( rm )
        conn.SetEnd( delta_c[1] )
        self.board.Add(conn)
        self.group.AddItem(conn)

        conn = pcbnew.PCB_TRACK(self.board)
        conn.SetLayer(pcbnew.B_Cu)
        conn.SetWidth(self.trk_w)
        conn.SetStart( re )
        conn.SetEnd( delta_c[2] )
        self.board.Add(conn)
        self.group.AddItem(conn)

        return 0

    def do_thermal(self):
        # TODO:
        return 0

    def do_mounts(self):
        # TODO:
        return 0

    def do_outline(self, ro, rb):
        
        arc = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_ARC)
        arc.SetArcGeometry( 
            pcbnew.wxPoint( ro, 0),
            pcbnew.wxPoint( -ro, 0),
            pcbnew.wxPoint( ro,  0))
        arc.SetLayer( pcbnew.Edge_Cuts )
        self.board.Add(arc)
        self.group.AddItem(arc)
        
        arc = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_ARC)
        arc.SetArcGeometry( 
            pcbnew.wxPoint( rb, 0),
            pcbnew.wxPoint( -rb, 0),
            pcbnew.wxPoint( rb, 0))
        arc.SetLayer( pcbnew.Edge_Cuts )
        self.board.Add(arc)
        self.group.AddItem(arc)


    # tests
    def test(self):
        
        fill = int(self.m_ctrlRfill.GetValue() * 1e6)

        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart( pcbnew.wxPointMM(-1,11) )
        t.SetEnd( pcbnew.wxPointMM(-2,57) )
        self.board.Add(t)
        t1 = pcbnew.PCB_ARC(self.board)
        t1.SetStart( pcbnew.wxPointMM(-2,57) )
        t1.SetMid( pcbnew.wxPointMM(-29,51) )
        t1.SetEnd( pcbnew.wxPointMM(-48,30) )
        self.board.Add(t1)
        t2 = pcbnew.PCB_TRACK(self.board)
        t2.SetStart( pcbnew.wxPointMM(-48,30) )
        t2.SetEnd( pcbnew.wxPointMM(-8,8) )
        self.board.Add(t2)
        kf.fillet(self.board, t,t1, fill)
        kf.fillet(self.board, t1,t2, fill)



        # t1 = pcbnew.PCB_TRACK(self.board)
        # t1.SetStart( pcbnew.wxPointMM(10,-10) )
        # t1.SetEnd( pcbnew.wxPointMM(110,-60) )
        # self.board.Add(t1)
        # t2 = pcbnew.PCB_TRACK(self.board)
        # t2.SetStart( pcbnew.wxPointMM(110,-60) )
        # t2.SetEnd( pcbnew.wxPointMM(110,60) )
        # self.board.Add(t2)
        # t3 = pcbnew.PCB_TRACK(self.board)
        # t3.SetStart( pcbnew.wxPointMM(110,60) )
        # t3.SetEnd( pcbnew.wxPointMM(10,-10) )
        # self.board.Add(t3)
        # kf.fillet(self.board, t1,t2, fill)
        # kf.fillet(self.board, t2,t3, fill)


        # ## square (pos XY, CCW)
        # t = pcbnew.PCB_TRACK(self.board)
        # t.SetStart( pcbnew.wxPointMM(10,10) )
        # t.SetEnd( pcbnew.wxPointMM(60,10) )
        # self.board.Add(t)
        # t1 = pcbnew.PCB_TRACK(self.board)
        # t1.SetStart( pcbnew.wxPointMM(60,10) )
        # t1.SetEnd( pcbnew.wxPointMM(60,60) )
        # self.board.Add(t1)
        # t2 = pcbnew.PCB_TRACK(self.board)
        # t2.SetStart( pcbnew.wxPointMM(60,60) )
        # t2.SetEnd( pcbnew.wxPointMM(10,60) )
        # self.board.Add(t2)
        # t3 = pcbnew.PCB_TRACK(self.board)
        # t3.SetStart( pcbnew.wxPointMM(10,60) )
        # t3.SetEnd( pcbnew.wxPointMM(10,10) )
        # self.board.Add(t3)
        # kf.fillet(self.board, t, t1, fill)
        # kf.fillet(self.board, t1, t2, fill)
        # kf.fillet(self.board, t2, t3, fill)

        ## square (pos XY, CW)
        # t = pcbnew.PCB_TRACK(self.board)
        # t.SetStart( pcbnew.wxPointMM(110,10) )
        # t.SetEnd( pcbnew.wxPointMM(110,60) )
        # self.board.Add(t)
        # t1 = pcbnew.PCB_TRACK(self.board)
        # t1.SetStart( pcbnew.wxPointMM(110,60) )
        # t1.SetEnd( pcbnew.wxPointMM(160,60) )
        # self.board.Add(t1)
        # t2 = pcbnew.PCB_TRACK(self.board)
        # t2.SetStart( pcbnew.wxPointMM(160,60) )
        # t2.SetEnd( pcbnew.wxPointMM(160,10) )
        # self.board.Add(t2)
        # t3 = pcbnew.PCB_TRACK(self.board)
        # t3.SetStart( pcbnew.wxPointMM(160,10) )
        # t3.SetEnd( pcbnew.wxPointMM(110,10) )
        # self.board.Add(t3)
        # kf.fillet(self.board, t, t1, fill)
        # kf.fillet(self.board, t1, t2, fill)
        # kf.fillet(self.board, t2, t3, fill)


        ## angles
        # t = pcbnew.PCB_TRACK(self.board)
        # t.SetStart( pcbnew.wxPointMM(100,0) )
        # t.SetEnd( pcbnew.wxPointMM(150,50) )
        # self.board.Add(t)
        # t1 = pcbnew.PCB_TRACK(self.board)
        # t1.SetStart( pcbnew.wxPointMM(150,50) )
        # t1.SetEnd( pcbnew.wxPointMM(200,50) )
        # self.board.Add(t1)
        # t2 = pcbnew.PCB_TRACK(self.board)
        # t2.SetStart( pcbnew.wxPointMM(200,50) )
        # t2.SetEnd( pcbnew.wxPointMM(150,0) )
        # self.board.Add(t2)
        # kf.fillet(self.board, t,t1, fill)
        # kf.fillet(self.board, t1,t2, fill)



        #track3 = pcbnew.PCB_ARC(self.board)
        #track3.SetStart( pcbnew.wxPointMM(0,100) )
        #track3.SetEnd( pcbnew.wxPointMM(0,50) )
        #track3.SetMid( pcbnew.wxPointMM(-25,75) )
        #self.board.Add(track3)

        #fill = self.fillet(track, track2, 10)
        #self.board.Add(fill)
        
        #kf.do_fillet(self.board, track, track2, 10*1e6)

        #fill2 = self.fillet(track2, track3, 10)
        #self.board.Add(fill2)
        #self.do_fillet(track2, track3, 10*1e6)



        # update board
        pcbnew.Refresh()

