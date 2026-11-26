/* std_lin_bus.c - see std_lin_bus.h */
#include <string.h>
#include "std_lin_bus.h"

static boolean s_txConfirm = TRUE;

void StdLin_SetTxConfirm(boolean confirm) { s_txConfirm = confirm; }

uint8 StdLin_Pid(uint8 frameId)
{
    uint8 id = (uint8)(frameId & 0x3Fu);
    uint8 b0 = (uint8)(id & 1u), b1 = (uint8)((id >> 1) & 1u), b2 = (uint8)((id >> 2) & 1u);
    uint8 b3 = (uint8)((id >> 3) & 1u), b4 = (uint8)((id >> 4) & 1u), b5 = (uint8)((id >> 5) & 1u);
    uint8 p0 = (uint8)(b0 ^ b1 ^ b2 ^ b4);
    uint8 p1 = (uint8)(1u ^ (b1 ^ b3 ^ b4 ^ b5));
    return (uint8)(id | (uint8)(p0 << 6) | (uint8)(p1 << 7));
}

StdLinResult StdLin_HeaderPid(uint8 pid)
{
    StdLinResult r;
    uint8 buf[8];
    Lin_PduType pdu;
    memset(&r, 0, sizeof r);
    memset(buf, 0xA5, sizeof buf);               /* poison: unwritten bytes are visible */
    pdu.Pid = pid;
    pdu.Cs = LIN_ENHANCED_CS;
    pdu.Drc = LIN_FRAMERESPONSE_IGNORE;
    pdu.Dl = 8u;
    pdu.SduPtr = buf;
    r.ret = LinIf_HeaderIndication(STD_LIN_CHANNEL, &pdu);
    r.dl = (uint8)pdu.Dl;
    r.cs = (uint8)pdu.Cs;
    if (r.ret == E_OK && pdu.Drc == LIN_FRAMERESPONSE_TX) {
        r.transmitted = TRUE;
        memcpy(r.data, pdu.SduPtr ? pdu.SduPtr : buf, 8u);
        if (s_txConfirm) {
            LinIf_TxConfirmation(STD_LIN_CHANNEL);
        }
    } else if (r.ret == E_OK && pdu.Drc == LIN_FRAMERESPONSE_RX) {
        r.subscribed = TRUE;
    }
    return r;
}

StdLinResult StdLin_Header(uint8 frameId) { return StdLin_HeaderPid(StdLin_Pid(frameId)); }

StdLinResult StdLin_Rx(uint8 frameId, const uint8 data[8])
{
    uint8 tmp[8];
    StdLinResult r = StdLin_Header(frameId);
    if (r.subscribed) {
        memcpy(tmp, data, 8u);
        LinIf_RxIndication(STD_LIN_CHANNEL, tmp);
    }
    return r;
}

StdLinResult StdLin_RxError(uint8 frameId, Lin_SlaveErrorType err)
{
    StdLinResult r = StdLin_Header(frameId);
    if (r.subscribed || r.transmitted) {
        LinIf_LinErrorIndication(STD_LIN_CHANNEL, err);
    }
    return r;
}
