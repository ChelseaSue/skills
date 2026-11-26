/* std_lin_bus.h - LIN bus simulation for host tests of an AUTOSAR LIN slave stack (LinIf 4.4 slave API).
 *
 * The test plays the LIN driver: it delivers headers and responses to LinIf exactly as Lin.c would
 * (LinIf_HeaderIndication -> LinIf_RxIndication / LinIf_TxConfirmation / LinIf_LinErrorIndication).
 * Nothing here is project specific; the channel defaults to 0 (override STD_LIN_CHANNEL).
 */
#ifndef STD_LIN_BUS_H
#define STD_LIN_BUS_H

#include "Std_Types.h"
#include "ComStack_Types.h"
#include "LinIf_Cbk.h"

#ifndef STD_LIN_CHANNEL
#define STD_LIN_CHANNEL 0u
#endif

typedef struct {
    Std_ReturnType ret;          /* return value of LinIf_HeaderIndication */
    boolean        transmitted;  /* LinIf asked to publish a response (this node is the publisher) */
    boolean        subscribed;   /* LinIf expects to receive the response */
    uint8          dl;           /* data length requested by LinIf */
    uint8          cs;           /* checksum model requested by LinIf (Lin_FrameCsModelType) */
    uint8          data[8];      /* published response bytes (valid when transmitted) */
} StdLinResult;

uint8 StdLin_Pid(uint8 frameId);                         /* 6-bit id -> protected id (parity bits) */
StdLinResult StdLin_HeaderPid(uint8 pid);                /* raw PID, e.g. to inject a parity error */
StdLinResult StdLin_Header(uint8 frameId);               /* header; if this node publishes, take the response and confirm it */
StdLinResult StdLin_Rx(uint8 frameId, const uint8 data[8]);           /* header + correct response to a subscribed frame */
StdLinResult StdLin_RxError(uint8 frameId, Lin_SlaveErrorType err);   /* header + erroneous response */
void StdLin_SetTxConfirm(boolean confirm);               /* FALSE: published responses are not confirmed (TX failure) */

#endif /* STD_LIN_BUS_H */
